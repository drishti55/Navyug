import pandas as pd
from datetime import datetime, timedelta
import imaplib
import email
import re
from dateutil import parser 

import dspy
from dspy_components.signatures import EmailIntentExtraction, ConversationSummarization

from modules.utils import ( 
    _alert_human_review, 
    STATE_PENDING, STATE_FILLED, STATE_RESUBMITTED, 
    STATE_NEEDS_HUMAN_REVIEW, STATE_OUT_OF_OFFICE, STATE_CANNOT_QUOTE
)
from modules.handle_quote_submitted import handle_quote_submitted
from modules.handle_out_of_office import handle_out_of_office
from modules.handle_cannot_quote import handle_cannot_quote
from modules.handle_date_provided import handle_date_provided
from modules.handle_acknowledgment import handle_acknowledgment
from modules.handle_needs_assistance_or_unclear_other import handle_needs_assistance_or_unclear_other


classify_predictor = dspy.Predict(EmailIntentExtraction)
summarize_predictor = dspy.Predict(ConversationSummarization)


def extract_uuid_from_subject(subject):
    """Extracts a UUID from the email subject if present."""
    match = re.search(r'Form ID: ([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', subject)
    if match:
        return match.group(1)
    return None

def format_original_message(original_body, original_from, original_date, subject):
    """Formats the original message for quoting in replies/alerts."""
    header = f"\n\n--- Original message from {original_from} on {original_date} ---\n"
    quoted_body = "\n".join([f"> {line}" for line in original_body.splitlines()])
    footer = f"\n--- End of Original message ---\n"
    return f"{header}{quoted_body}{footer}"


def process_single_incoming_email(email_info, quotations_df, merged_df_for_ref, calendar_service, send_email_func, HUMAN_REVIEW_EMAIL):
    """
    Processes a single incoming email, classifies its intent, and dispatches to appropriate handlers.
    Updates the quotations_df based on the email's content and intent.
    """
    email_subject = email_info['subject']
    email_body = email_info['body']
    original_message_id = email_info['message_id']
    original_references = email_info['references']
    original_from = email_info['from']
    original_date = email_info['date']

    print(f"\n--- Processing Incoming Email from: {original_from} (Subject: '{email_subject}') ---")
    print(f"DEBUG: Original Message-ID: {original_message_id}")
    print(f"DEBUG: Original References: {original_references}")

    linked_uuid = extract_uuid_from_subject(email_subject)
    quotation_row_index = None
    linked_quotation_id = None
    items_requested = "N/A - No linked quotation" 

    if linked_uuid:
        matching_quotes = quotations_df[quotations_df['uuid'] == linked_uuid]
        if not matching_quotes.empty:
            quotation_row_index = matching_quotes.index[0]
            linked_quotation_id = quotations_df.loc[quotation_row_index, 'id']
            items_requested = quotations_df.loc[quotation_row_index, 'items_requested']
            print(f"Email linked to Quotation ID: {linked_quotation_id} (UUID: {linked_uuid})")
        else:
            print(f"WARNING: UUID '{linked_uuid}' found in subject but no matching quotation in DB. Cannot link directly.")
    else:
        print("No parsable UUID found in email subject. Cannot link directly to a specific quote.")

    try:
        prediction = classify_predictor(email_subject=email_subject, email_body=email_body)
        intent = prediction.intent.strip().upper()
        extracted_date_str = prediction.extracted_date
        
        if intent != "DATE_PROVIDED" or (extracted_date_str and extracted_date_str.lower() == 'null'):
            extracted_date = None
        else:
            try:
                extracted_date = parser.parse(extracted_date_str).date() if extracted_date_str else None
                if extracted_date and (extracted_date < (datetime.now().date() - timedelta(days=365)) or \
                                        extracted_date > (datetime.now().date() + timedelta(days=365 * 2))):
                    print(f"WARNING: Extracted date {extracted_date} seems out of reasonable range (past year or next two years). Treating as unextractable.")
                    extracted_date = None
            except (ValueError, parser.ParserError): 
                print(f"WARNING: Could not parse DSPy extracted date '{extracted_date_str}' using dateutil.parser. Setting to None.")
                extracted_date = None

    except Exception as e:
        print(f"ERROR: Error classifying email intent with DSPy: {e}")
        intent = "UNCLEAR_OTHER"
        extracted_date = None


    print(f"LLM classified intent as: {intent}")
    if extracted_date:
        print(f"LLM extracted date: {extracted_date.strftime('%Y-%m-%d')}")

    update_required = False
    new_state = None
    alert_subject = None
    alert_body = None
    alert_human = False 

    relevant_indent_id = "N/A"
    if linked_quotation_id:
        indent_row = merged_df_for_ref[merged_df_for_ref['id'] == linked_quotation_id]
        if not indent_row.empty:
            relevant_indent_id = indent_row['indent_id'].iloc[0]

    quote_original_in_reply = (original_message_id and intent in ["DATE_PROVIDED", "NEEDS_ASSISTANCE", "UNCLEAR_OTHER", "ACKNOWLEDGMENT"])

    quoted_message_for_reply = ""
    if quote_original_in_reply:
        quoted_message_for_reply = format_original_message(email_body, original_from, original_date, email_subject)

    if intent == "QUOTE_SUBMITTED":
        quotations_df, update_required, alert_human, new_state, alert_subject, alert_body = \
            handle_quote_submitted(
                quotations_df, quotation_row_index, linked_quotation_id, relevant_indent_id,
                original_from, email_subject, original_message_id, original_references,
                send_email_func, HUMAN_REVIEW_EMAIL
            )

    elif intent == "OUT_OF_OFFICE":
        quotations_df, update_required, alert_human, new_state, alert_subject, alert_body = \
            handle_out_of_office(
                quotations_df, quotation_row_index, linked_quotation_id, relevant_indent_id,
                original_from, email_subject, original_message_id, original_references,
                send_email_func, HUMAN_REVIEW_EMAIL
            )

    elif intent == "CANNOT_QUOTE":
        quotations_df, update_required, alert_human, new_state, alert_subject, alert_body = \
            handle_cannot_quote(
                quotations_df, quotation_row_index, linked_quotation_id, relevant_indent_id,
                original_from, email_subject, original_message_id, original_references,
                send_email_func, HUMAN_REVIEW_EMAIL
            )

    elif intent == "DATE_PROVIDED":
        quotations_df, update_required, alert_human, new_state, alert_subject, alert_body = \
            handle_date_provided(
                quotations_df, quotation_row_index, linked_quotation_id, relevant_indent_id,
                original_from, email_subject, original_message_id, original_references,
                send_email_func, calendar_service, extracted_date, items_requested,
                quoted_message_for_reply
            )

    elif intent == "ACKNOWLEDGMENT":
        temp_df, update_required, alert_human, new_state, alert_subject, alert_body = \
            handle_acknowledgment(
                original_from, email_subject, original_message_id, original_references,
                send_email_func, quoted_message_for_reply
            )
        if temp_df is not None:
            quotations_df = temp_df
        
    elif intent == "NEEDS_ASSISTANCE" or intent == "UNCLEAR_OTHER":
        quotations_df, update_required, alert_human, new_state, alert_subject, alert_body = \
            handle_needs_assistance_or_unclear_other(
                quotations_df, quotation_row_index, linked_quotation_id, relevant_indent_id,
                original_from, email_subject, original_message_id, original_references,
                send_email_func, intent, quoted_message_for_reply,
                HUMAN_REVIEW_EMAIL
            )
    else:
        print(f"Action: Unhandled intent '{intent}' from {original_from}. Flagging for human review.")
        alert_human = True
        alert_subject = f"ACTION REQUIRED: Unhandled Intent - From: {original_from} (Indent: {relevant_indent_id})"
        alert_body = f"The Automated Follow-Up system received an email with an unhandled intent '{intent}'. Please review.\n\nOriginal Email:\nFrom: {original_from}\nSubject: {email_subject}\nBody:\n{email_body}"
        if quotation_row_index is not None:
            quotations_df.loc[quotation_row_index, 'needs_human_review'] = True
            new_state = STATE_NEEDS_HUMAN_REVIEW 
            update_required = True


    if alert_human:
        print(f"DEBUG: Attempting to retrieve past conversations for Indent ID {relevant_indent_id} and vendor {original_from}")
        
        conversation_summary_text = "No previous relevant conversation found."
        
        try:
            retrieved_conversations_result = None 

            if isinstance(retrieved_conversations_result, str): 
                print(f"WARNING: Conversation retrieval returned an error: {retrieved_conversations_result}")
                conversation_summary_text = f"Error retrieving previous conversations: {retrieved_conversations_result}"
            elif retrieved_conversations_result and hasattr(retrieved_conversations_result, 'conversations') and retrieved_conversations_result.conversations:
                all_turns_text = ""
                for conv in retrieved_conversations_result.conversations:
                    for turn in conv.turns:
                        all_turns_text += f"User: {turn.request}\n"
                        all_turns_text += f"Model: {turn.response}\n"
                
                if all_turns_text.strip(): 
                    print("DEBUG: Summarizing retrieved conversation turns.")
                    summarization_prediction = summarize_predictor(conversation_turns=all_turns_text)
                    conversation_summary_text = summarization_prediction.summary.strip()
                    if not conversation_summary_text:
                        conversation_summary_text = "No meaningful summary could be generated from previous conversations."
                else:
                    conversation_summary_text = "No recent conversation turns found for summarization."
            else:
                print("DEBUG: No conversations retrieved by conversation_retrieval tool.")

        except Exception as e:
            print(f"ERROR: Failed to retrieve or summarize past conversations: {e}")
            conversation_summary_text = f"Failed to retrieve or summarize previous conversation due to an error: {e}"

        _alert_human_review(send_email_func, HUMAN_REVIEW_EMAIL, alert_subject, alert_body, 
                            original_from, email_subject, original_date, email_body, 
                            linked_quotation_id, relevant_indent_id, conversation_summary_text)
    
    if quotation_row_index is not None:
        if update_required:
            quotations_df.loc[quotation_row_index, 'state'] = new_state
            quotations_df.loc[quotation_row_index, 'needs_human_review'] = (new_state == STATE_NEEDS_HUMAN_REVIEW)
        elif alert_human and quotations_df.loc[quotation_row_index, 'needs_human_review'] == False:
             quotations_df.loc[quotation_row_index, 'needs_human_review'] = True
    
    return quotations_df


def fetch_and_process_inbox_emails(quotations_df, merged_df_for_ref, calendar_service, send_email_func, HUMAN_REVIEW_EMAIL, IMAP_SERVER, IMAP_PORT, INBOX_EMAIL, INBOX_PASSWORD):
    """
    Connects to the IMAP inbox, fetches unread emails, and processes them.
    Dispatches each email to process_single_incoming_email.
    """
    print("\n--- Starting Incoming Email Processing ---")
    processed_count = 0
    mail = None
    try:
        print(f"DEBUG: Attempting to connect to IMAP server: {IMAP_SERVER}:{IMAP_PORT}")
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        print("DEBUG: Connected to IMAP server.")
        
        print(f"DEBUG: Attempting to login with email: {INBOX_EMAIL}")
        mail.login(INBOX_EMAIL, INBOX_PASSWORD)
        print("DEBUG: Logged in to IMAP successfully.")

        print("DEBUG: Selecting 'inbox' folder.")
        status, messages = mail.select('inbox')
        if status != 'OK':
            print(f"ERROR: Could not select inbox. Status: {status}, Messages: {messages}")
            return quotations_df
        print("DEBUG: Inbox selected successfully.")

        print("DEBUG: Searching for UNSEEN emails.")
        status, email_ids = mail.search(None, 'UNSEEN')
        if status != 'OK':
            print(f"ERROR: Could not search for UNSEEN emails. Status: {status}")
            return quotations_df
        
        email_id_list = email_ids[0].split()

        if not email_id_list:
            print("No new/unread emails found in inbox.")
            return quotations_df

        print(f"Found {len(email_id_list)} new/unread emails in inbox based on IMAP search.")

        for num in email_id_list:
            print(f"DEBUG: Fetching email ID: {num.decode('utf-8')}")
            status, msg_data = mail.fetch(num, '(RFC822)')
            if status != 'OK':
                print(f"ERROR: Failed to fetch email {num}. Status: {status}")
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            email_info = {
                'id': num.decode('utf-8'),
                'from': msg['from'],
                'subject': msg['subject'],
                'date': msg['date'],
                'body': '', 
                'message_id': msg['Message-ID'] if 'Message-ID' in msg else None,
                'references': msg['References'] if 'References' in msg else None
            }

            if msg.is_multipart():
                for part in msg.walk():
                    ctype = part.get_content_type()
                    cdisp = str(part.get('Content-Disposition'))
                    if ctype == 'text/plain' and 'attachment' not in cdisp:
                        try:
                            charset = part.get_content_charset() or 'utf-8'
                            email_info['body'] = part.get_payload(decode=True).decode(charset, errors='ignore')
                            break
                        except Exception as e:
                            print(f"WARNING: Error decoding text/plain part (multipart): {e}")
                            email_info['body'] = part.get_payload(decode=True).decode(errors='ignore')
                            break
            else:
                try:
                    charset = msg.get_content_charset() or 'utf-8'
                    email_info['body'] = msg.get_payload(decode=True).decode(charset, errors='ignore')
                except Exception as e:
                    print(f"WARNING: Error decoding single part email: {e}")
                    email_info['body'] = msg.get_payload(decode=True).decode(errors='ignore')

            quotations_df = process_single_incoming_email(email_info, quotations_df, merged_df_for_ref, calendar_service, send_email_func, HUMAN_REVIEW_EMAIL)
            processed_count += 1
            
            mail.store(num, '+FLAGS', '\\Seen')
            print(f"DEBUG: Email ID {email_info['id']} (Subject: '{email_info['subject'][:50]}...') marked as read.")

    except imaplib.IMAP4.error as e:
        print(f"CRITICAL ERROR: IMAP connection or authentication failed. Check INBOX_EMAIL/INBOX_PASSWORD or App Password. Error: {e}")
    except Exception as e:
        print(f"CRITICAL ERROR during incoming email processing (fetch_and_process_inbox_emails): {e}")
    finally:
        if mail:
            try:
                mail.logout()
                print("DEBUG: Logged out from IMAP server.")
            except Exception as e:
                print(f"WARNING: Error during IMAP logout: {e}")
    
    print(f"--- Finished processing {processed_count} incoming emails. ---")
    return quotations_df
