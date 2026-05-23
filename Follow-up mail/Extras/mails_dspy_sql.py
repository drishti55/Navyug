import os
import pandas as pd
import google.generativeai as genai
from datetime import datetime, timedelta
import smtplib
import dspy
from email.mime.text import MIMEText
from email.header import Header
import imaplib
import email
import re
import json
from dateutil import parser  
import psycopg2 

print("DEBUG: Script execution started at the very beginning of the file.")

API_KEY = os.getenv("GOOGLE_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
INBOX_EMAIL = os.getenv("INBOX_EMAIL")
INBOX_PASSWORD = os.getenv("INBOX_PASSWORD")
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", 993))
HUMAN_REVIEW_EMAIL = os.getenv("HUMAN_REVIEW_EMAIL", "procurement.team@navyuginfosolutions.com")

PG_DB_HOST = os.getenv("PG_DB_HOST", "localhost")
PG_DB_NAME = os.getenv("PG_DB_NAME", "procurement_db")
PG_DB_USER = os.getenv("PG_DB_USER", "postgres")
PG_DB_PASSWORD = os.getenv("PG_DB_PASSWORD", "password") 
PG_DB_PORT = os.getenv("PG_DB_PORT", "5432")

if not API_KEY:
    print("ERROR: GOOGLE_API_KEY environment variable is NOT set. Please set it.")
    raise ValueError("GOOGLE_API_KEY environment variable not set. Please set your API key.")
if not SENDER_EMAIL or not SENDER_PASSWORD:
    print("ERROR: SENDER_EMAIL or SENDER_PASSWORD environment variables are NOT set. Please set them.")
    raise ValueError("SENDER_EMAIL and SENDER_PASSWORD environment variables not set. Please set them for real email sending.")
if not INBOX_EMAIL or not INBOX_PASSWORD:
    print("ERROR: INBOX_EMAIL or INBOX_PASSWORD environment variables are NOT set. Please set them.")
    raise ValueError("INBOX_EMAIL and INBOX_PASSWORD environment variables not set. Please set them for email reading.")
if not HUMAN_REVIEW_EMAIL:
    print("ERROR: HUMAN_REVIEW_EMAIL environment variable is NOT set. Please set it.")
    raise ValueError("HUMAN_REVIEW_EMAIL environment variable not set. Please set it for human review alerts.")
if not all([PG_DB_HOST, PG_DB_NAME, PG_DB_USER, PG_DB_PASSWORD, PG_DB_PORT]):
    print("ERROR: One or more PostgreSQL environment variables (PG_DB_HOST, PG_DB_NAME, PG_DB_USER, PG_DB_PASSWORD, PG_DB_PORT) are NOT set. Please configure them.")
    raise ValueError("PostgreSQL environment variables not set.")

print("DEBUG: All Configuration Variables are set and validated.")
print(f"DEBUG: SENDER_EMAIL: {SENDER_EMAIL}")
print(f"DEBUG: INBOX_EMAIL: {INBOX_EMAIL}")
print(f"DEBUG: HUMAN_REVIEW_EMAIL: {HUMAN_REVIEW_EMAIL}")
print(f"DEBUG: PG_DB_NAME: {PG_DB_NAME}, PG_DB_USER: {PG_DB_USER}, PG_DB_HOST: {PG_DB_HOST}")


print("DEBUG: Attempting to configure DSPy LM...")
dspy.settings.configure(lm=dspy.LM(model='gemini/gemini-1.5-flash', api_key=API_KEY))
print("DEBUG: DSPy configured successfully.")


DAYS_OVERDUE_THRESHOLD = 7
DAYS_BETWEEN_REMINDERS = 3
STATE_PENDING = 1
STATE_FILLED = 2
STATE_RESUBMITTED = 3
STATE_NEEDS_HUMAN_REVIEW = 4
STATE_OUT_OF_OFFICE = 5
STATE_CANNOT_QUOTE = 6

class EmailIntentExtraction(dspy.Signature):
    """Classify the intent of an incoming supplier email and extract a submission date if applicable.
    The extracted date must be the most likely submission date mentioned in the email,  in YYYY-MM-DD format.
    If no clear date is mentioned, or if the intent is not DATE_PROVIDED, set extracted_date to null.
    
    The intent must be one of: QUOTE_SUBMITTED, OUT_OF_OFFICE, CANNOT_QUOTE, DATE_PROVIDED, NEEDS_ASSISTANCE, UNCLEAR_OTHER, ACKNOWLEDGMENT.
    
    Examples:
    Email: Subject: "Quote attached for ID 123", Body: "Here's the final quote. Thanks." -> Intent: QUOTE_SUBMITTED
    Email: Subject: "RE: Your Inquiry", Body: "I am out of office until next week." -> Intent: OUT_OF_OFFICE
    Email: Subject: "Cannot provide quote for Widget X", Body: "We do not carry these specific parts. Apologies." -> Intent: CANNOT_QUOTE
    Email: Subject: "Problem with Form ID: ABCD", Body: "The upload button is not working. I can't attach my quote." -> Intent: NEEDS_ASSISTANCE
    Email: Subject: "Question about specifications", Body: "Can you clarify the dimensions for item 5? We need assistance." -> Intent: NEEDS_ASSISTANCE
    Email: Subject: "Expected submission date", Body: "We will submit the quote by 2025-07-30." -> Intent: DATE_PROVIDED, extracted_date: 2025-07-30
    Email: Subject: "Thanks for the info", Body: "Noted with thanks." -> Intent: ACKNOWLEDGMENT
    Email: Subject: "Free vacation!", Body: "Click here to claim your prize." -> Intent: UNCLEAR_OTHER
    """
    email_subject: str = dspy.InputField(desc="Subject of the email")
    email_body: str = dspy.InputField(desc="Body of the email")
    
    intent: str = dspy.OutputField(desc="Primary intent of the email.")
    extracted_date: str = dspy.OutputField(desc="Most likely submission date in YYYY-MM-DD format, or null.")

classify_predictor = dspy.Predict(EmailIntentExtraction)


class ConversationSummarization(dspy.Signature):
    """Summarize the provided conversation turns into a concise overview, focusing on the vendor's primary query, problem, or request for assistance. Highlight relevant details like specific issues, items, or dates mentioned in their request.

    Examples:
    Conversation:
    User: Can you clarify the dimensions for item 5? We need assistance.
    Model: Dear Vendor, Thank you for your message... Your query requires human attention...
    Summary: The vendor needs clarification on the dimensions for item 5 of the quotation.

    Conversation:
    User: The file size for attachment is too small on your form. Can't upload our full quote.
    Model: Dear Vendor, Thank you for your message... Your query requires human attention...
    Summary: The vendor is encountering a technical issue where the form's attachment file size limit is too small to upload their full quote.

    Conversation:
    User: We'll submit by 2025-07-15.
    Model: Dear Vendor, Thank you for your update... We have noted your expected submission date...
    Summary: The vendor provided an expected submission date of 2025-07-15.

    Conversation:
    User: Noted with thanks.
    Model: Dear Vendor, Thank you for your message. We are glad to hear from you...
    Summary: The vendor sent a simple acknowledgment of the previous communication.
    """
    conversation_turns: str = dspy.InputField(desc="Concatenated text of conversation turns")
    
    summary: str = dspy.OutputField(desc="A concise summary of the conversation, specifically detailing the vendor's request or problem.")

summarize_predictor = dspy.Predict(ConversationSummarization)


def send_email(to_email, subject, body, in_reply_to_id=None, references_ids=None):
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['From'] = SENDER_EMAIL
    msg['To'] = to_email
    
    if in_reply_to_id and not subject.lower().startswith('re:'):
        msg['Subject'] = Header(f"Re: {subject}", 'utf-8')
    else:
        msg['Subject'] = Header(subject, 'utf-8')

    if in_reply_to_id:
        msg['In-Reply-To'] = in_reply_to_id
        print(f"DEBUG: Setting In-Reply-To: {in_reply_to_id}")
    if references_ids:
        # Join existing references and the new In-Reply-To ID
        if in_reply_to_id and in_reply_to_id not in references_ids.split():
            # Ensure the ID being replied to is also in references for proper threading
            msg['References'] = f"{references_ids} {in_reply_to_id}"
        else:
            msg['References'] = references_ids
        print(f"DEBUG: Setting References: {msg['References']}")

    try:
        print(f"DEBUG: Attempting to send email to {to_email} with Subject: '{subject}'...")
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        print(f"SUCCESS: Email sent to {to_email} with Subject: '{subject}'")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"CRITICAL ERROR: SMTP Authentication failed for {SENDER_EMAIL}. Check SENDER_PASSWORD or App Password. Error: {e}")
        return False
    except smtplib.SMTPServerDisconnected as e:
        print(f"CRITICAL ERROR: SMTP server disconnected unexpectedly. Error: {e}")
        return False
    except smtplib.SMTPException as e:
        print(f"ERROR: SMTP error occurred while sending email to {to_email}. Error: {e}")
        return False
    except Exception as e:
        print(f"ERROR: An unexpected error occurred while sending email to {to_email}. Error: {e}")
        return False

def generate_follow_up_email(vendor_name, indent_id, items_requested, original_request_date, form_link, quotation_uuid):
    items_str = str(items_requested)
    subject_template = f"Gentle Reminder: Quotation Request (Form ID: {quotation_uuid}) for Indent ID {indent_id} - Navyug Infosolutions"

    prompt_content = f"""
    You are an AI assistant for a procurement platform. Your task is to draft a polite and professional follow-up email to a vendor who has not yet submitted a quotation.

    Here are the details for the quotation request:
    - Vendor Company Name: {vendor_name}
    - Our Company Name: Navyug Infosolutions
    - Indent ID: {indent_id}
    - Items Requested: {items_str}
    - Original Request Date: {original_request_date}
    - Quotation Form Link: {form_link}

    Please draft an email reminding them to submit their quotation. The email should:
    1. Be polite and professional.
    2. Clearly state the purpose (follow-up on quotation).
    3. Reference the Indent ID and items requested.
    4. Remind of importance of timely response.
    5. Clearly include the provided "Quotation Form Link" and instruct them to click it to submit.
    6. Offer assistance if facing issues.
    7. Keep the tone helpful and cooperative.
    8. Include a polite closing from "Navyug Infosolutions Procurement Team".

    The email subject has already been generated as: "{subject_template}"
    Provide only the Body of the email.
    """

    try:
        raw_response = dspy.settings.lm(prompt=prompt_content)
        
        if isinstance(raw_response, list) and raw_response:
            body_content = raw_response[0].strip()
        elif hasattr(raw_response, 'completions') and raw_response.completions:
            body_content = raw_response.completions[0].strip()
        elif hasattr(raw_response, 'text') and raw_response.text:
            body_content = raw_response.text.strip()
        else:
            raise ValueError("Unexpected LLM response format: No text content found.")

        return subject_template, body_content
    except Exception as e:
        print(f"Error generating email with LLM: {e}")
        return f"ERROR: Could not generate email for Form ID: {quotation_uuid}", f"An error occurred while generating the email content. Details: {e}"


def extract_uuid_from_subject(subject):
    match = re.search(r'Form ID: ([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', subject)
    if match:
        return match.group(1)
    return None

def format_original_message(original_body, original_from, original_date, subject):
    header = f"\n\n--- Original message from {original_from} on {original_date} ---\n"
    quoted_body = "\n".join([f"> {line}" for line in original_body.splitlines()])
    footer = f"\n--- End of Original message ---\n"
    return f"{header}{quoted_body}{footer}"


def process_single_incoming_email(email_info, quotations_df, merged_df_for_ref):
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
    if linked_uuid:
        matching_quotes = quotations_df[quotations_df['uuid'] == linked_uuid]
        if not matching_quotes.empty:
            quotation_row_index = matching_quotes.index[0]
            linked_quotation_id = quotations_df.loc[quotation_row_index, 'id']
            print(f"Email linked to Quotation ID: {linked_quotation_id} (UUID: {linked_uuid})")
        else:
            print(f"WARNING: UUID '{linked_uuid}' found in subject but no matching quotation in DB. Cannot link directly.")
    else:
        print("No parsable UUID found in email subject. Cannot link directly to a specific quote.")

    try:
        prediction = classify_predictor(email_subject=email_subject, email_body=email_body)
        intent = prediction.intent.strip().upper()
        extracted_date_str = prediction.extracted_date
        
        if extracted_date_str and extracted_date_str.lower() == 'null':
            extracted_date = None
        else:
            try:
                extracted_date = parser.parse(extracted_date_str).date() if extracted_date_str else None
                if extracted_date and (extracted_date < (datetime.now().date() - timedelta(days=365)) or \
                                       extracted_date > (datetime.now().date() + timedelta(days=365 * 2))):
                    print(f"WARNING: Extracted date {extracted_date} seems out of reasonable range (past year or next two years). Treating as unextractable.")
                    extracted_date = None
            except (ValueError, parser.ParserError): # Catch dateutil's specific error as well
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
    alert_human = False
    alert_subject = "Automated Procurement System Alert"
    alert_body = "" 

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
        if quotation_row_index is not None:
            new_state = STATE_RESUBMITTED
            update_required = True
            print(f"Action: Quotation {linked_quotation_id} marked as RESUBMITTED.")
            auto_reply_subject = email_subject
            auto_reply_body = f"""
Dear Vendor,

Thank you for submitting your quotation for Indent ID {relevant_indent_id}. We appreciate your response and will process it shortly.

Best regards,

Navyug Infosolutions Procurement Team
"""
            print(f"DEBUG: Attempting to send auto-reply for QUOTE_SUBMITTED to {original_from} with threading headers.")
            send_email(original_from, auto_reply_subject, auto_reply_body, original_message_id, original_references)

        else:
            print("Action: QUOTE_SUBMITTED but no linked quotation. Flagging for human review.")
            alert_human = True
            alert_subject = f"ACTION REQUIRED: Quote Submitted, No Link - From: {original_from}"
            alert_body = f"An email indicating quote submission was received from {original_from}, but no linked quotation ID could be found.\n\nOriginal Email:\nFrom: {original_from}\nSubject: {email_subject}\nBody:\n{email_body}"

    elif intent == "OUT_OF_OFFICE":
        if quotation_row_index is not None:
            new_state = STATE_OUT_OF_OFFICE
            update_required = True
            print(f"Action: Quotation {linked_quotation_id} marked as OUT_OF_OFFICE.")
            auto_reply_subject = email_subject
            auto_reply_body = f"""
Dear Vendor,

Thank you for your out-of-office reply. We have noted your return date and will be waiting for your quotation for Indent ID {relevant_indent_id} upon your return.

Best regards,

Navyug Infosolutions Procurement Team
""" 
            print(f"DEBUG: Attempting to send auto-reply for OUT_OF_OFFICE to {original_from} with threading headers.")
            send_email(original_from, auto_reply_subject, auto_reply_body, original_message_id, original_references)
        else:
            print(f"Action: OUT_OF_OFFICE email from {original_from}. No linked quotation, so no DB update. Informing human.")
            alert_human = True
            alert_subject = f"INFO: Out of Office Reply (Unlinked) - From: {original_from}"
            alert_body = f"An Out of Office reply was received from {original_from}. No linked quotation ID. For your information.\n\nOriginal Email:\nFrom: {original_from}\nSubject: {email_subject}\nBody:\n{email_body}"

    elif intent == "CANNOT_QUOTE":
        if quotation_row_index is not None:
            new_state = STATE_CANNOT_QUOTE
            update_required = True
            print(f"Action: Quotation {linked_quotation_id} marked as CANNOT_QUOTE.")
            auto_reply_subject = email_subject
            auto_reply_body = f"""
Dear Vendor,

Thank you for letting us know that you are unable to provide a quotation for Indent ID {relevant_indent_id}. We appreciate you taking the time to respond.

Best regards,

Navyug Infosolutions Procurement Team
"""
            print(f"DEBUG: Attempting to send auto-reply for CANNOT_QUOTE to {original_from} with threading headers.")
            send_email(original_from, auto_reply_subject, auto_reply_body, original_message_id, original_references)
        else:
            print(f"Action: CANNOT_QUOTE email from {original_from}. No linked quotation. Flagging for human review.")
            alert_human = True
            alert_subject = f"ACTION REQUIRED: 'Cannot Quote' received, No Link - From: {original_from}"
            alert_body = f"A 'Cannot Quote' email was received from {original_from}, but no linked quotation ID. Please review.\n\nOriginal Email:\nFrom: {original_from}\nSubject: {email_subject}\nBody:\n{email_body}"

    elif intent == "DATE_PROVIDED":
        if quotation_row_index is not None and extracted_date:
            # Case 1: Linked and date successfully parsed
            quotations_df.loc[quotation_row_index, 'expected_submission_date'] = extracted_date.strftime('%Y-%m-%d')
            new_state = STATE_PENDING 
            update_required = True
            print(f"Action: Quotation {linked_quotation_id} updated with expected submission date: {extracted_date.strftime('%Y-%m-%d')}.")
            auto_reply_subject = email_subject
            auto_reply_body = f"""
Dear Vendor,

Thank you for your update regarding quotation for Indent ID {relevant_indent_id}. We have noted your expected submission date as {extracted_date.strftime('%Y-%m-%d')}. We will remind you closer to that date if needed.

We appreciate your timely communication.

Best regards,

Navyug Infosolutions Procurement Team
{quoted_message_for_reply if quote_original_in_reply else ""}
""" 
            print(f"DEBUG: Attempting to send auto-reply for DATE_PROVIDED to {original_from} with threading headers.")
            send_email(original_from, auto_reply_subject, auto_reply_body, original_message_id, original_references)

        elif quotation_row_index is not None: 
            # Case 2: Linked but date extraction failed - Send reply to vendor, alert human
            print(f"Action: DATE_PROVIDED for {original_from} but date extraction failed. Flagging for human review and sending a basic reply to vendor.")
            alert_human = True
            quotations_df.loc[quotation_row_index, 'needs_human_review'] = True
            if quotations_df.loc[quotation_row_index, 'state'] != STATE_NEEDS_HUMAN_REVIEW:
                quotations_df.loc[quotation_row_index, 'state'] = STATE_NEEDS_HUMAN_REVIEW

            alert_subject = f"ACTION REQUIRED: Date Provided (Unparsed) - From: {original_from} (Indent: {relevant_indent_id})"
            alert_body = f"A supplier has indicated a submission date ({original_from}) but the date could not be automatically parsed." 
            
            auto_reply_subject = email_subject
            auto_reply_body = f"""
Dear Vendor,

Thank you for your update regarding the expected submission date for Indent ID {relevant_indent_id}. We were unable to automatically process the date provided and will review your message manually. We will be in touch if we require further clarification.

Best regards,

Navyug Infosolutions Procurement Team
{quoted_message_for_reply if quote_original_in_reply else ""}
"""
            print(f"DEBUG: Attempting to send auto-reply for DATE_PROVIDED (unparsed) to {original_from} with threading headers.")
            send_email(original_from, auto_reply_subject, auto_reply_body, original_message_id, original_references)

        else: 
            # Case 3: No linked quotation for DATE_PROVIDED - Only alert human
            print(f"Action: DATE_PROVIDED for {original_from} but no link. Needs human to confirm/extract date AND link to a quote.")
            alert_human = True
            alert_subject = f"ACTION REQUIRED: Date Provided (Unlinked) - From: {original_from}"
            alert_body = f"A supplier has indicated a submission date ({original_from}) but no linked quotation ID could be found." 

    # Handle ACKNOWLEDGMENT intent
    elif intent == "ACKNOWLEDGMENT":
        print(f"Action: Email from {original_from} classified as 'ACKNOWLEDGMENT'. Sending a polite reply.")

        auto_reply_subject = email_subject 
        auto_reply_body = f"""
Dear Vendor,

Thank you for your message. We are glad to hear from you and appreciate your communication.

Best regards,

Navyug Infosolutions Procurement Team
{quoted_message_for_reply if quote_original_in_reply else ""}
"""
        print(f"DEBUG: Attempting to send auto-reply for ACKNOWLEDGMENT to {original_from} with threading headers.")
        send_email(original_from, auto_reply_subject, auto_reply_body, original_message_id, original_references)

    # Existing: NEEDS_ASSISTANCE and UNCLEAR_OTHER
    elif intent == "NEEDS_ASSISTANCE" or intent == "UNCLEAR_OTHER":
        print(f"Action: Email from {original_from} classified as '{intent}'. Flagging for human review.")
        alert_human = True
        if quotation_row_index is not None:
            quotations_df.loc[quotation_row_index, 'needs_human_review'] = True
            if new_state not in [STATE_FILLED, STATE_RESUBMITTED, STATE_CANNOT_QUOTE, STATE_OUT_OF_OFFICE]:
                new_state = STATE_NEEDS_HUMAN_REVIEW
                update_required = True 
        
        auto_reply_subject = email_subject
        auto_reply_body = f"""
Dear Vendor,

Thank you for your message regarding Indent ID {relevant_indent_id}. Your query requires human attention and has been flagged for our procurement team's review.

We will get back to you as soon as possible.

Best regards,

Navyug Infosolutions Procurement Team
{quoted_message_for_reply if quote_original_in_reply else ""}
"""
        print(f"DEBUG: Attempting to send auto-reply for '{intent}' to {original_from} with threading headers.")
        send_email(original_from, auto_reply_subject, auto_reply_body, original_message_id, original_references)
        
        alert_subject = f"ACTION REQUIRED: Supplier Reply Needs Review - From: {original_from} (Indent: {relevant_indent_id})"
        alert_body = f"The Automated Follow-Up system has received a supplier reply that requires your immediate attention. The AI classified this email as: **{intent}**."



    if alert_human:
        # Step 1: Retrieve relevant past conversations
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

        final_alert_body = f"""
Dear Team,

{alert_body}

--- Conversation Summary ---
{conversation_summary_text}
--- End Conversation Summary ---

--- Original Message Details (requiring review) ---
From: {original_from}
Subject: {email_subject}
Date Received: {original_date}

Original Message:
{email_body}
--- End Original Message Details ---

Internal Reference (if linked):
Quotation ID: {linked_quotation_id if linked_quotation_id else 'Not Linked'}
Vendor Email: {original_from}
Indent ID: {relevant_indent_id}
# Add a link to the internal dashboard here if you have one.
# Example: Link to internal dashboard for this quote/indent if applicable: https://yourcompany.com/dashboard/quotes/{linked_quotation_id}

Please investigate and reply directly to the supplier as needed.

Thank you,
Navyug Infosolutions Automated Procurement System
"""
        print(f"DEBUG: Sending human review alert to {HUMAN_REVIEW_EMAIL} for subject: {alert_subject[:70]}...")
        send_email(HUMAN_REVIEW_EMAIL, alert_subject, final_alert_body) 
    


    if quotation_row_index is not None:
        if update_required:
            quotations_df.loc[quotation_row_index, 'state'] = new_state
            quotations_df.loc[quotation_row_index, 'needs_human_review'] = (new_state == STATE_NEEDS_HUMAN_REVIEW)
        elif alert_human and quotations_df.loc[quotation_row_index, 'needs_human_review'] == False:
             quotations_df.loc[quotation_row_index, 'needs_human_review'] = True
    
    return quotations_df

def fetch_and_process_inbox_emails(quotations_df, merged_df_for_ref):
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

            quotations_df = process_single_incoming_email(email_info, quotations_df, merged_df_for_ref)
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

def run_daily_automation():
    print("--- Starting Daily Automated Procurement Workflow ---")
    current_time = datetime.now()
    print(f"Current System Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        quotations_df = pd.read_csv('quotations.csv', sep=',')
        vendor_contacts_df = pd.read_csv('vendor_contacts.csv', sep=',')
    except FileNotFoundError as e:
        print(f"CRITICAL ERROR: CSV file not found. Make sure 'quotations.csv' and 'vendor_contacts.csv' are in the same directory as the script.")
        print(f"Details: {e}")
        return

    quotations_df['created_at'] = pd.to_datetime(quotations_df['created_at'], errors='coerce')
    quotations_df['updated_at'] = pd.to_datetime(quotations_df['updated_at'], errors='coerce')
    quotations_df['last_reminder_sent_at'] = pd.to_datetime(quotations_df['last_reminder_sent_at'], errors='coerce')
    quotations_df['expected_submission_date'] = pd.to_datetime(quotations_df['expected_submission_date'], errors='coerce')
    
    quotations_df['needs_human_review'] = quotations_df['needs_human_review'].astype(bool)

    quotations_df['vendor_id'] = quotations_df['vendor_id'].astype(str)
    vendor_contacts_df['vendor_id'] = vendor_contacts_df['vendor_id'].astype(str)

    merged_df = pd.merge(
        quotations_df,
        vendor_contacts_df,
        on='vendor_id',
        how='left'
    )
    
    print("\n--- DEBUG: quotations_df head after loading and initial type conversion ---")
    print(quotations_df.head().to_markdown(index=False, numalign="left", stralign="left"))
    print("\n--- DEBUG: Merged DataFrame head for reference ---")
    print(merged_df.head().to_markdown(index=False, numalign="left", stralign="left"))
    print("---------------------------------------------------------------------------\n")

    print("\n--- Phase 1: Sending Automated Follow-Ups ---")
    overdue_quotes_to_process = []

    for index, row in merged_df.iterrows():
        original_quotations_df_index = quotations_df[quotations_df['id'] == row['id']].index[0]

        if pd.isna(row['created_at']):
            print(f"Skipping quotation {row['id']}: 'created_at' date parsing failed or is missing.")
            continue
        if pd.isna(row['vendor_email']):
            print(f"Skipping quotation {row['id']} (Indent: {row['indent_id']}): Vendor email not found for vendor_id {row['vendor_id']}. Please update vendor_contacts.csv.")
            quotations_df.loc[original_quotations_df_index, 'needs_human_review'] = True
            if quotations_df.loc[original_quotations_df_index, 'state'] != STATE_NEEDS_HUMAN_REVIEW:
                quotations_df.loc[original_quotations_df_index, 'state'] = STATE_NEEDS_HUMAN_REVIEW
            send_email(HUMAN_REVIEW_EMAIL, f"ACTION REQUIRED: Missing Vendor Email for Quote ID {row['id']}",
                       f"Vendor email is missing for Quotation ID {row['id']} (Indent: {row['indent_id']}). Please update vendor_contacts.csv. Original Request Date: {row['created_at'].strftime('%Y-%m-%d')}")
            continue
        
        if row['state'] != STATE_PENDING or row['needs_human_review']:
            print(f"Skipping quotation {row['id']} (Indent: {row['indent_id']}): State is {row['state']} or needs_human_review={row['needs_human_review']}.")
            continue

        days_since_created = (current_time - row['created_at']).days

        if days_since_created >= DAYS_OVERDUE_THRESHOLD:
            if pd.isna(row['last_reminder_sent_at']):
                print(f"Quotation {row['id']} (Indent: {row['indent_id']}) is overdue ({days_since_created} days). No reminder sent yet. Adding to reminders list.")
                overdue_quotes_to_process.append(row)
            else:
                days_since_last_reminder = (current_time - row['last_reminder_sent_at']).days
                if days_since_last_reminder >= DAYS_BETWEEN_REMINDERS:
                    print(f"Quotation {row['id']} (Indent: {row['indent_id']}) is overdue ({days_since_created} days) and reminder threshold met ({days_since_last_reminder} days since last). Adding to reminders list.")
                    overdue_quotes_to_process.append(row)
                else:
                    print(f"Quotation {row['id']} (Indent: {row['indent_id']}) is overdue but too soon to send another reminder ({days_since_last_reminder} days since last).")
        else:
            print(f"Quotation {row['id']} (Indent: {row['indent_id']}) is not yet overdue ({days_since_created} days).")


    print(f"Found {len(overdue_quotes_to_process)} quotations requiring outgoing follow-up.")

    if not overdue_quotes_to_process:
        print("No outgoing emails to send today.")
    else:
        for quote_data in overdue_quotes_to_process:
            vendor_name = quote_data['vendor_name']
            vendor_email = quote_data['vendor_email']
            indent_id = quote_data['indent_id']
            quotation_id = quote_data['id']
            items_requested = quote_data['items_requested']
            original_request_date = quote_data['created_at'].strftime('%Y-%m-%d')
            quotation_uuid = quote_data['uuid']
            form_link = f"https://yourcompany.com/quotes/form?id={quotation_uuid}"

            print(f"\n--- Sending Reminder for Quotation ID: {quotation_id} (Indent: {indent_id}) ---")
            print(f"Generating email for {vendor_name} ({vendor_email})...")

            subject, body = generate_follow_up_email(
                vendor_name,
                indent_id,
                items_requested,
                original_request_date,
                form_link,
                quotation_uuid
            )

            print(f"Generated Subject: {subject}")
            print(f"Generated Body (first 200 chars):\\n{body[:200]}...")

            email_sent_successfully = send_email(vendor_email, subject, body)

            if email_sent_successfully:
                current_row_index = quotations_df[quotations_df['id'] == quotation_id].index[0]
                quotations_df.loc[current_row_index, 'last_reminder_sent_at'] = current_time
                print(f"LOG: Updated last_reminder_sent_at for quotation ID {quotation_id} to {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                print(f"WARNING: Outgoing email for quotation ID {quotation_id} failed to send. last_reminder_sent_at NOT updated. Flagging for human review.")
                current_row_index = quotations_df[quotations_df['id'] == quotation_id].index[0]
                quotations_df.loc[current_row_index, 'needs_human_review'] = True
                if quotations_df.loc[current_row_index, 'state'] != STATE_NEEDS_HUMAN_REVIEW:
                    quotations_df.loc[current_row_index, 'state'] = STATE_NEEDS_HUMAN_REVIEW
                send_email(HUMAN_REVIEW_EMAIL, f"ACTION REQUIRED: Failed to Send Reminder for Quote ID {quotation_id}",
                           f"The system failed to send a reminder email to {vendor_email} for Quotation ID {quotation_id} (Indent: {indent_id}). Please review.\n\nSubject: {subject}\nBody:\n{body}")
        
    print("\n--- Phase 2: Processing Incoming Emails (Smart Inbox) ---")
    quotations_df = fetch_and_process_inbox_emails(quotations_df, merged_df)

    quotations_df['created_at'] = quotations_df['created_at'].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
    quotations_df['updated_at'] = quotations_df['updated_at'].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
    quotations_df['last_reminder_sent_at'] = quotations_df['last_reminder_sent_at'].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
    quotations_df['expected_submission_date'] = quotations_df['expected_submission_date'].dt.strftime('%Y-%m-%d').fillna('')
    
    quotations_df['needs_human_review'] = quotations_df['needs_human_review'].astype(bool)

    print("\n--- DEBUG: quotations_df head before final saving ---")
    print(quotations_df.head().to_markdown(index=False, numalign="left", stralign="left"))
    
    try:
        quotations_df.to_csv('quotations.csv', index=False)
        print("\n--- SUCCESS: Updated 'quotations.csv' with latest timestamps and states ---")
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to save 'quotations.csv'. Please check file permissions or if the file is open. Error: {e}")

    print("--- Daily Automated Procurement Workflow Finished ---")

if __name__ == "__main__":
    run_daily_automation()