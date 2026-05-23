import os
import pandas as pd
import google.generativeai as genai
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.header import Header
import imaplib
import email
import re 


API_KEY = os.getenv("GOOGLE_API_KEY")

SENDER_EMAIL = os.getenv("SENDER_EMAIL") 
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD") 
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com") 
SMTP_PORT = int(os.getenv("SMTP_PORT", 587)) 

INBOX_EMAIL = os.getenv("INBOX_EMAIL")
INBOX_PASSWORD = os.getenv("INBOX_PASSWORD") 
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com") 
IMAP_PORT = int(os.getenv("IMAP_PORT", 993)) 


HUMAN_REVIEW_EMAIL = os.getenv("HUMAN_REVIEW_EMAIL", "procurement.team@yourcompany.com") # CHANGE THIS to a real address for your team!

if not API_KEY:
    raise ValueError("GOOGLE_API_KEY environment variable not set. Please set your API key.")
if not SENDER_EMAIL or not SENDER_PASSWORD:
    raise ValueError("SENDER_EMAIL and SENDER_PASSWORD environment variables not set. Please set them for real email sending.")
if not INBOX_EMAIL or not INBOX_PASSWORD:
    raise ValueError("INBOX_EMAIL and INBOX_PASSWORD environment variables not set. Please set them for email reading.")
if not HUMAN_REVIEW_EMAIL:
    raise ValueError("HUMAN_REVIEW_EMAIL environment variable not set. Please set it for human review alerts.")

genai.configure(api_key=API_KEY)
llm_model = genai.GenerativeModel('gemini-1.5-flash')


DAYS_OVERDUE_THRESHOLD = 7
DAYS_BETWEEN_REMINDERS = 3 


STATE_PENDING = 1
STATE_FILLED = 2
STATE_CANNOT_QUOTE = 3
STATE_NEEDS_HUMAN_REVIEW = 4
STATE_OUT_OF_OFFICE = 5



def send_email(to_email, subject, body):
    """
    Sends an email using the configured SMTP server.
    """
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['From'] = SENDER_EMAIL
    msg['To'] = to_email
    msg['Subject'] = Header(subject, 'utf-8')

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        print(f"SUCCESS: Email sent to {to_email} with Subject: '{subject}'")
        return True
    except Exception as e:
        print(f"ERROR: Failed to send email to {to_email}. Error: {e}")
        return False

def generate_follow_up_email(vendor_name, indent_id, items_requested, original_request_date, form_link, quotation_uuid):
    """
    Generates a follow-up email using the LLM, embedding the UUID in the subject.
    """
    items_str = str(items_requested)


    subject_template = f"Gentle Reminder: Quotation Request (Form ID: {quotation_uuid}) for Indent ID {indent_id} - Navyug Infosolutions"

    prompt = f"""
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
    2. Clearly state the purpose of the email (follow-up on quotation).
    3. Reference the Indent ID and the items requested.
    4. Remind them of the importance of their timely response.
    5. Clearly include the provided "Quotation Form Link" and instruct them to click it to submit their quotation.
    6. Offer assistance if they are facing any issues.
    7. Keep the tone helpful and cooperative.
    8. Include a polite closing from "Navyug Infosolutions Procurement Team".

    The email subject has already been generated as: "{subject_template}"
    Provide only the Body of the email.
    """

    try:
        response = llm_model.generate_content(prompt)
        body_content = response.text.strip()
        return subject_template, body_content
    except Exception as e:
        print(f"Error generating email with LLM: {e}")
        return f"ERROR: Could not generate email for Form ID: {quotation_uuid}", f"An error occurred while generating the email content. Details: {e}"

def classify_email_intent(email_subject, email_body):
    """
    Uses LLM to classify the intent of an incoming supplier email.
    """
    prompt = f"""
    You are an AI assistant designed to classify the intent of incoming supplier email replies for a procurement system.
    Analyze the following email subject and body and determine its primary intent.
    Return only one of the following labels:
    - QUOTE_SUBMITTED: The supplier has indicated they submitted the quote or it's attached.
    - OUT_OF_OFFICE: An automatic "out of office" reply.
    - CANNOT_QUOTE: Supplier explicitly states they cannot provide a quote.
    - DATE_PROVIDED: Supplier gives a specific date for submission (e.g., "will send by July 20").
    - NEEDS_ASSISTANCE: Supplier indicates they need help with the form or have a question.
    - UNCLEAR_OTHER: The LLM cannot confidently categorize the email, or it's a general, unclassifiable reply.

    Email Subject: {email_subject}
    Email Body:
    {email_body}

    Intent:
    """
    try:
        response = llm_model.generate_content(prompt)
        intent = response.text.strip().upper().replace("INTENT:", "").strip()
        valid_intents = ["QUOTE_SUBMITTED", "OUT_OF_OFFICE", "CANNOT_QUOTE", "DATE_PROVIDED", "NEEDS_ASSISTANCE", "UNCLEAR_OTHER"]
        if intent not in valid_intents:
            print(f"WARNING: LLM returned unexpected intent '{intent}'. Defaulting to UNCLEAR_OTHER.")
            return "UNCLEAR_OTHER"
        return intent
    except Exception as e:
        print(f"Error classifying email intent with LLM: {e}")
        return "UNCLEAR_OTHER" # Fallback if LLM call fails

def extract_uuid_from_subject(subject):
    """
    Attempts to extract a UUID from the email subject line.
    Assumes UUID is in the format 'Form ID: [UUID]' (e.g., in a reply "Re: Gentle Reminder... (Form ID: UUID)")
    """
    match = re.search(r'Form ID: ([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', subject)
    if match:
        return match.group(1)
    return None

def process_single_incoming_email(email_info, quotations_df, merged_df_for_ref):
    """
    Processes a single incoming email: classifies intent, updates DB, sends alerts.
    Takes quotations_df (to update) and merged_df_for_ref (for lookup)
    """
    email_subject = email_info['subject']
    email_body = email_info['body']
    from_email = email_info['from']

    print(f"\n--- Processing Incoming Email from: {from_email} (Subject: '{email_subject}') ---")


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

    intent = classify_email_intent(email_subject, email_body)
    print(f"LLM classified intent as: {intent}")

    update_required = False
    new_state = None
    needs_human_review = False
    alert_human = False
    alert_subject = "Automated Procurement System Alert"
    alert_body = ""

    relevant_indent_id = "N/A"
    if linked_quotation_id:
        indent_row = merged_df_for_ref[merged_df_for_ref['id'] == linked_quotation_id]
        if not indent_row.empty:
            relevant_indent_id = indent_row['indent_id'].iloc[0]


    if intent == "QUOTE_SUBMITTED":
        if quotation_row_index is not None:
            new_state = STATE_FILLED
            update_required = True
            print(f"Action: Quotation {linked_quotation_id} marked as FILLED.")
        else:
            print("Action: QUOTE_SUBMITTED but no linked quotation. Flagging for human review.")
            alert_human = True
            alert_subject = f"ACTION REQUIRED: Quote Submitted, No Link - From: {from_email}"
            alert_body = f"An email indicating quote submission was received from {from_email}, but no linked quotation ID could be found. Please review.\n\nOriginal Email:\nFrom: {from_email}\nSubject: {email_subject}\nBody:\n{email_body}"

    elif intent == "OUT_OF_OFFICE":
        if quotation_row_index is not None:
            new_state = STATE_OUT_OF_OFFICE 
            update_required = True
            print(f"Action: Quotation {linked_quotation_id} marked as OUT_OF_OFFICE.")
            auto_reply_subject = f"Re: Your Out of Office - Navyug Infosolutions Procurement for Indent ID {relevant_indent_id}"
            auto_reply_body = f"""
Dear Vendor,

Thank you for your out-of-office reply. We have noted your return date and will adjust our follow-up schedule regarding quotation for Indent ID {relevant_indent_id}.

Best regards,

Navyug Infosolutions Procurement Team
"""
            send_email(from_email, auto_reply_subject, auto_reply_body)

        else:
            print(f"Action: OUT_OF_OFFICE email from {from_email}. No linked quotation, so no DB update.")
            alert_human = True 
            alert_subject = f"INFO: Out of Office Reply - From: {from_email}"
            alert_body = f"An Out of Office reply was received from {from_email}. No linked quotation ID. FYI.\n\nOriginal Email:\nSubject: {email_subject}\nBody:\n{email_body}"

    elif intent == "CANNOT_QUOTE":
        if quotation_row_index is not None:
            new_state = STATE_CANNOT_QUOTE
            update_required = True
            print(f"Action: Quotation {linked_quotation_id} marked as CANNOT_QUOTE.")
            auto_reply_subject = f"Re: Your Quotation Request - Navyug Infosolutions for Indent ID {relevant_indent_id}"
            auto_reply_body = f"""
Dear Vendor,

Thank you for letting us know that you are unable to provide a quotation for Indent ID {relevant_indent_id}. We appreciate you taking the time to respond.

Best regards,

Navyug Infosolutions Procurement Team
"""
            send_email(from_email, auto_reply_subject, auto_reply_body)
        else:
            print(f"Action: CANNOT_QUOTE email from {from_email}. No linked quotation. Flagging for human review.")
            alert_human = True
            alert_subject = f"ACTION REQUIRED: 'Cannot Quote' received, No Link - From: {from_email}"
            alert_body = f"A 'Cannot Quote' email was received from {from_email}, but no linked quotation ID. Please review.\n\nOriginal Email:\nSubject: {email_subject}\nBody:\n{email_body}"

    elif intent == "DATE_PROVIDED":
        print(f"Action: DATE_PROVIDED for {from_email}. Needs human to confirm/extract date for now.")
        alert_human = True
        needs_human_review = True
        alert_subject = f"ACTION REQUIRED: Date Provided, Needs Date Extraction - From: {from_email} (Indent: {relevant_indent_id})"
        alert_body = f"A supplier has provided a date for submission ({from_email}). Please extract the date and update the quotation record.\n\nOriginal Email:\nSubject: {email_subject}\nBody:\n{email_body}"

    elif intent == "NEEDS_ASSISTANCE" or intent == "UNCLEAR_OTHER":
        print(f"Action: Email from {from_email} classified as '{intent}'. Flagging for human review.")
        alert_human = True
        needs_human_review = True
        alert_subject = f"ACTION REQUIRED: Supplier Reply Needs Review - From: {from_email} (Indent: {relevant_indent_id})"
        alert_body = f"""
        Dear Procurement Team,

        The Automated Follow-Up system has received a supplier reply that requires your immediate attention. The AI classified this email as: **{intent}**.

        Please review the original supplier's message below to understand their query or intent and take appropriate action.

        ---
        Original Supplier Details:
        From: {from_email}
        Subject: {email_subject}
        Date Received: {email_info['date']}

        ---
        Original Supplier Message:
        {email_body}
        ---

        Internal Reference (if linked):
        Quotation ID: {linked_quotation_id if linked_quotation_id else 'Not Linked'}
        Vendor Email: {from_email}
        Indent ID: {relevant_indent_id}
        # Add a link to the internal dashboard here if you have one.
        # Example: Link to internal dashboard for this quote/indent if applicable: https://yourcompany.com/dashboard/quotes/{linked_quotation_id}

        Please investigate and reply directly to the supplier as needed.

        Thank you,
        Navyug Infosolutions Automated Procurement System
        """

    if update_required and quotation_row_index is not None:
        quotations_df.loc[quotation_row_index, 'state'] = new_state
        quotations_df.loc[quotation_row_index, 'needs_human_review'] = False 
    
    if needs_human_review and quotation_row_index is not None:
        quotations_df.loc[quotation_row_index, 'needs_human_review'] = True
        if new_state not in [STATE_FILLED, STATE_CANNOT_QUOTE, STATE_OUT_OF_OFFICE]:
            quotations_df.loc[quotation_row_index, 'state'] = STATE_NEEDS_HUMAN_REVIEW
        else: 
            pass 
    elif quotation_row_index is not None: 
         quotations_df.loc[quotation_row_index, 'needs_human_review'] = False


    if alert_human:
        send_email(HUMAN_REVIEW_EMAIL, alert_subject, alert_body)
    
    return quotations_df 

def fetch_and_process_inbox_emails(quotations_df, merged_df_for_ref):
    """
    Connects to the IMAP server, fetches unread emails,
    classifies them, and triggers actions/updates.
    """
    print("\n--- Starting Incoming Email Processing ---")
    processed_count = 0
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(INBOX_EMAIL, INBOX_PASSWORD)
        mail.select('inbox')

        status, email_ids = mail.search(None, 'UNSEEN')
        email_id_list = email_ids[0].split()

        print(f"Found {len(email_id_list)} new/unread emails in inbox.")

        for num in email_id_list:
            status, msg_data = mail.fetch(num, '(RFC822)')
            if status != 'OK':
                print(f"Failed to fetch email {num}. Status: {status}")
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            email_info = {
                'id': num.decode('utf-8'),
                'from': msg['from'],
                'subject': msg['subject'],
                'date': msg['date'],
                'body': ''
            }

            if msg.is_multipart():
                for part in msg.walk():
                    ctype = part.get_content_type()
                    cdisp = str(part.get('Content-Disposition'))
                    if ctype == 'text/plain' and 'attachment' not in cdisp:
                        try:
                            email_info['body'] = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore')
                            break 
                        except Exception as e:
                            print(f"Error decoding multipart part: {e}")
                            email_info['body'] = part.get_payload(decode=True).decode(errors='ignore')
            else: 
                try:
                    email_info['body'] = msg.get_payload(decode=True).decode(msg.get_content_charset() or 'utf-8', errors='ignore')
                except Exception as e:
                    print(f"Error decoding single part email: {e}")
                    email_info['body'] = msg.get_payload(decode=True).decode(errors='ignore')

            quotations_df = process_single_incoming_email(email_info, quotations_df, merged_df_for_ref)
            processed_count += 1
            
            mail.store(num, '+FLAGS', '\\Seen')
            print(f"Email {email_info['id']} marked as read.")

        mail.logout()
        print(f"--- Finished processing {processed_count} incoming emails. ---")
    except Exception as e:
        print(f"An error occurred during incoming email processing: {e}")
    
    return quotations_df 

def run_daily_automation():
    print("--- Starting Daily Automated Procurement Workflow ---")
    current_time = datetime.now()
    print(f"Current System Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        quotations_df = pd.read_csv('quotations.csv', sep=',')
        vendor_contacts_df = pd.read_csv('vendor_contacts.csv', sep=',')
    except FileNotFoundError as e:
        print(f"Error: CSV file not found. Make sure 'quotations.csv' and 'vendor_contacts.csv' are in the same directory as the script.")
        print(f"Details: {e}")
        return

    quotations_df['created_at'] = pd.to_datetime(quotations_df['created_at'], errors='coerce')
    quotations_df['updated_at'] = pd.to_datetime(quotations_df['updated_at'], errors='coerce')
    quotations_df['last_reminder_sent_at'] = pd.to_datetime(quotations_df['last_reminder_sent_at'], errors='coerce')
    
    quotations_df['needs_human_review'] = quotations_df['needs_human_review'].astype(bool)

    quotations_df['vendor_id'] = quotations_df['vendor_id'].astype(str)
    vendor_contacts_df['vendor_id'] = vendor_contacts_df['vendor_id'].astype(str)

    merged_df = pd.merge(
        quotations_df,
        vendor_contacts_df,
        on='vendor_id',
        how='left'
    )
    
    print("\n--- DEBUG: DataFrame head after loading ---")
    print(quotations_df.head().to_markdown(index=False, numalign="left", stralign="left"))
    print("-------------------------------------------\n")

    print("\n--- Phase 1: Sending Automated Follow-Ups ---")
    overdue_quotes_to_process = []

    for index, row in merged_df.iterrows():
        if pd.isna(row['created_at']):
            print(f"Skipping quotation {row['id']}: 'created_at' date parsing failed.")
            continue
        if pd.isna(row['vendor_email']):
            print(f"Skipping quotation {row['id']}: Vendor email not found for vendor_id {row['vendor_id']}.")
            continue
        
        if row['state'] != STATE_PENDING or row['needs_human_review']:
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
                print(f"WARNING: Outgoing email for quotation ID {quotation_id} failed to send. last_reminder_sent_at NOT updated.")
    
    print("\n--- Phase 2: Processing Incoming Emails (Smart Inbox) ---")
    quotations_df = fetch_and_process_inbox_emails(quotations_df, merged_df) 

    quotations_df['created_at'] = quotations_df['created_at'].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
    quotations_df['updated_at'] = quotations_df['updated_at'].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
    quotations_df['last_reminder_sent_at'] = quotations_df['last_reminder_sent_at'].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
    
    quotations_df['needs_human_review'] = quotations_df['needs_human_review'].astype(bool)

    quotations_df.to_csv('quotations.csv', index=False)
    print("\n--- Updated 'quotations.csv' with latest timestamps and states ---")
    print("--- Daily Automated Procurement Workflow Finished ---")

if __name__ == "__main__":
    run_daily_automation()