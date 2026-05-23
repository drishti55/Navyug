import os
import pandas as pd
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText 
from email.header import Header 
import dspy 
from dateutil import parser 

import pickle 
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from dspy_components.signatures import EmailIntentExtraction, ConversationSummarization
from modules.utils import (
    _alert_human_review, 
    STATE_PENDING, STATE_FILLED, STATE_RESUBMITTED, 
    STATE_NEEDS_HUMAN_REVIEW, STATE_OUT_OF_OFFICE, STATE_CANNOT_QUOTE
)
from modules.outgoing_email_processor import process_outgoing_follow_ups
from modules.incoming_email_processor import fetch_and_process_inbox_emails

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

print("DEBUG: All Configuration Variables are set and validated.")
print(f"DEBUG: SENDER_EMAIL: {SENDER_EMAIL}")
print(f"DEBUG: INBOX_EMAIL: {INBOX_EMAIL}")
print(f"DEBUG: HUMAN_REVIEW_EMAIL: {HUMAN_REVIEW_EMAIL}")

print("DEBUG: Attempting to configure DSPy LM...")
dspy.settings.configure(lm=dspy.LM(model='gemini/gemini-1.5-flash', api_key=API_KEY))
print("DEBUG: DSPy configured successfully.")

classify_predictor = dspy.Predict(EmailIntentExtraction) 
summarize_predictor = dspy.Predict(ConversationSummarization) 

DAYS_OVERDUE_THRESHOLD = 7
DAYS_BETWEEN_REMINDERS = 3

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
        if in_reply_to_id and in_reply_to_id not in references_ids.split():
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

def evaluate_classification_model_from_csv(evaluation_csv_path):
    print(f"\n--- Starting Classification Model Evaluation from CSV: {evaluation_csv_path} ---")

    try:
        test_cases_df = pd.read_csv(evaluation_csv_path)
        required_cols = ['Vendor Reply Body', 'Human_Expected_Intent', 'Human_Expected_Date'] 
        if not all(col in test_cases_df.columns for col in required_cols):
            print(f"ERROR: Evaluation CSV must contain columns: {required_cols}")
            print(f"Found columns: {test_cases_df.columns.tolist()}")
            return 0.0, 0.0
    except FileNotFoundError:
        print(f"ERROR: Evaluation CSV file not found at {evaluation_csv_path}. Skipping evaluation.")
        return 0.0, 0.0
    except Exception as e:
        print(f"ERROR: Could not read or process evaluation CSV: {e}. Skipping evaluation.")
        return 0.0, 0.0

    correct_intent_predictions = 0
    correct_date_predictions = 0
    total_date_cases = 0
    
    print(f"Total test cases loaded from CSV: {len(test_cases_df)}\n")

    for i, row in test_cases_df.iterrows():
        subject = str(row['Vendor Reply Body']) 
        body = str(row['Vendor Reply Body']) 
        
        expected_intent = str(row['Human_Expected_Intent']).strip().upper() 
        expected_date_str = str(row['Human_Expected_Date']).strip() 

        expected_date = None
        if expected_date_str and expected_date_str.lower() != 'none' and expected_date_str.lower() != 'nan':
            try:
                expected_date = parser.parse(expected_date_str).strftime('%Y-%m-%d')
            except (ValueError, parser.ParserError):
                print(f"WARNING: Could not parse expected date '{expected_date_str}' in row {i+1}. Treating as None.")
                expected_date = None

        print(f"--- Test Case {i+1} ---")
        print(f"Subject (Used for AI Input): {subject[:50]}...")
        print(f"Body (Vendor Reply): {body[:100]}...")
        print(f"Expected Intent (Human): {expected_intent}")
        print(f"Expected Date (Human): {expected_date}\n")

        try:
            predicted_raw = classify_predictor(email_subject=subject, email_body=body) 
            predicted_intent = predicted_raw.intent.strip().upper()
            predicted_date_str = predicted_raw.extracted_date

            predicted_date = None
            if predicted_date_str and predicted_date_str.lower() != 'null':
                try:
                    predicted_date = parser.parse(predicted_date_str).strftime('%Y-%m-%d')
                except (ValueError, parser.ParserError):
                    predicted_date = "PARSE_ERROR" 

            print(f"Predicted Intent (AI): {predicted_intent}")
            print(f"Predicted Date (AI): {predicted_date}\n")

            intent_match = (predicted_intent == expected_intent)
            if intent_match:
                correct_intent_predictions += 1
                print("Intent Match: YES")
            else:
                print(f"Intent Match: NO (AI: {predicted_intent}, Human: {expected_intent})")
            
            if expected_date is not None:
                total_date_cases += 1
                date_match = (predicted_date == expected_date)
                if date_match:
                    correct_date_predictions += 1
                    print("Date Match: YES")
                else:
                    print(f"Date Match: NO (AI: {predicted_date}, Human: {expected_date})")
            else:
                print("Date Match: N/A (No human expected date)")
            
            print("-" * 30)

        except Exception as e:
            print(f"ERROR: Failed to process test case {i+1}: {e}")
            print("-" * 30)

    intent_accuracy = (correct_intent_predictions / len(test_cases_df)) * 100
    date_accuracy = (correct_date_predictions / total_date_cases) * 100 if total_date_cases > 0 else 0

    print("\n--- Evaluation Summary ---")
    print(f"Intent Classification Accuracy: {intent_accuracy:.2f}% ({correct_intent_predictions}/{len(test_cases_df)})")
    if total_date_cases > 0:
        print(f"Date Extraction Accuracy (for DATE_PROVIDED cases): {date_accuracy:.2f}% ({correct_date_predictions}/{total_date_cases})")
    else:
        print("No 'DATE_PROVIDED' cases with human expected dates in test set to evaluate date extraction.")
    print("--------------------------")

    print("\n--- End Classification Model Evaluation ---")
    return intent_accuracy, date_accuracy

def run_daily_automation():
    print("--- Starting Daily Automated Procurement Workflow ---")
    current_time = datetime.now() 
    print(f"Current System Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")

    SCOPES = ['https://www.googleapis.com/auth/calendar.events']
    calendar_service = None

    try:
        creds = None
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'client_secret.json', SCOPES)
                creds = flow.run_local_server(port=0)
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
        
        calendar_service = build('calendar', 'v3', credentials=creds)
        print("DEBUG: Google Calendar API service initialized successfully.")
    except HttpError as error:
        print(f"ERROR: An HTTP error occurred during Calendar API setup: {error}")
    except FileNotFoundError:
        print("ERROR: client_secret.json not found for Calendar API. Please ensure it's in the script directory.")
    except Exception as e:
        print(f"ERROR: Could not initialize Google Calendar API service: {e}")

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

    quotations_df = process_outgoing_follow_ups(
        quotations_df, merged_df, current_time, 
        DAYS_OVERDUE_THRESHOLD, DAYS_BETWEEN_REMINDERS, 
        send_email, HUMAN_REVIEW_EMAIL
    )
        
    quotations_df = fetch_and_process_inbox_emails(
        quotations_df, merged_df, calendar_service, send_email, HUMAN_REVIEW_EMAIL,
        IMAP_SERVER, IMAP_PORT, INBOX_EMAIL, INBOX_PASSWORD
    )

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
    evaluation_csv_filename = 'labeled_evaluation_data.csv' 

    print("\n\n#####################################################")
    print("### Running Email Intent Classification Evaluation ###")
    print("#####################################################")
    intent_acc, date_acc = evaluate_classification_model_from_csv(evaluation_csv_filename)
    print(f"\nOverall Intent Accuracy: {intent_acc:.2f}%")
    print(f"Overall Date Extraction Accuracy: {date_acc:.2f}%")
    print("\n#####################################################")
    print("### Starting Daily Automated Procurement Workflow ###")
    print("#####################################################\n")

    run_daily_automation()
