import os
import pandas as pd
import google.generativeai as genai
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.header import Header

API_KEY = os.getenv("GOOGLE_API_KEY")

# SMTP Email Sending Configuration 
SENDER_EMAIL = os.getenv("SENDER_EMAIL") 
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD") 
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com") 
SMTP_PORT = int(os.getenv("SMTP_PORT", 587)) 

if not API_KEY:
    raise ValueError("GOOGLE_API_KEY environment variable not set. Please set your API key.")
if not SENDER_EMAIL or not SENDER_PASSWORD:
    raise ValueError("SENDER_EMAIL and SENDER_PASSWORD environment variables not set. Please set them for real email sending.")


genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

#  Constants for Logic 
DAYS_OVERDUE_THRESHOLD = 7
DAYS_BETWEEN_REMINDERS = 3
QUOTATION_PENDING_STATE = 1 

#  Email Generation
def generate_follow_up_email(vendor_name, indent_id, items_requested, original_request_date, form_link):
    items_str = str(items_requested)

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
    8. Include a polite closing from "Navyug Infosolutions Team".

    Provide the Subject and Body of the email in a clear, easy-to-read format, separating them with a blank line after the subject.
    """

    try:
        response = model.generate_content(prompt)
        email_content = response.text.strip()
        subject_line = "No Subject Generated"
        body_content = email_content

        if "Subject:" in email_content:
            parts = email_content.split("Subject:", 1)
            if "Body:" in parts[1]:
                sub_body_parts = parts[1].split("Body:", 1)
                subject_line = sub_body_parts[0].strip()
                body_content = sub_body_parts[1].strip()
            else:
                lines = parts[1].split('\n\n', 1)
                if len(lines) > 1:
                    subject_line = lines[0].strip()
                    body_content = lines[1].strip()
                else:
                    subject_line = parts[1].strip().split('\n')[0]
                    body_content = parts[1].strip()
        return subject_line, body_content
    except Exception as e:
        print(f"Error generating email with LLM: {e}")
        return "ERROR: Could not generate email", f"An error occurred while generating the email content. Details: {e}"

# SMTP Email Sending Function 
def send_email_smtp(to_email, subject, body):
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
        print(f"SUCCESS: Email sent to {to_email} via SMTP. Subject: '{subject}'")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"ERROR: SMTP Authentication Failed for {to_email}. Check SENDER_EMAIL and SENDER_PASSWORD. Ensure App Password is used for Gmail/Outlook. Error: {e}")
        return False
    except smtplib.SMTPConnectError as e:
        print(f"ERROR: SMTP Connection Failed for {to_email}. Check SMTP_SERVER and SMTP_PORT. Error: {e}")
        return False
    except Exception as e:
        print(f"ERROR: Failed to send email to {to_email} via SMTP. General Error: {e}")
        return False

# Main 
def run_daily_follow_up_automation():
    print("--- Starting Daily Follow-Up Automation (CSV Mode) ---")
    current_time = datetime.now()
    print(f"Current System Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Load Data
    try:
        quotations_df = pd.read_csv('quotations.csv', sep=',')
        vendor_contacts_df = pd.read_csv('vendor_contacts.csv', sep=',')
    except FileNotFoundError as e:
        print(f"Error: CSV file not found. Make sure 'quotations.csv' and 'vendor_contacts.csv' are in the same directory as the script.")
        print(f"Details: {e}")
        return

    # Convert date/time columns to datetime objects.
    
    quotations_df['created_at'] = pd.to_datetime(quotations_df['created_at'], errors='coerce')
    quotations_df['updated_at'] = pd.to_datetime(quotations_df['updated_at'], errors='coerce')
    quotations_df['last_reminder_sent_at'] = pd.to_datetime(quotations_df['last_reminder_sent_at'], errors='coerce')

    
    print("\n--- DEBUG: DataFrame head after loading and initial date parsing ---")
    print(quotations_df.head().to_markdown(index=False, numalign="left", stralign="left"))
    print("------------------------------------------------------------------\n")
    


    #  Join Data
    quotations_df['vendor_id'] = quotations_df['vendor_id'].astype(str)
    vendor_contacts_df['vendor_id'] = vendor_contacts_df['vendor_id'].astype(str)

    merged_df = pd.merge(
        quotations_df,
        vendor_contacts_df,
        on='vendor_id',
        how='left'
    )

    # Identify Overdue & Remindable Quotations
    overdue_quotes_to_process = []

    for index, row in merged_df.iterrows():
        # Skip if crucial date parsing failed for this row
        if pd.isna(row['created_at']):
            print(f"Skipping quotation {row['id']}: 'created_at' date parsing failed, or row is malformed. Data: {row.to_dict()}")
            continue
        
        if pd.isna(row['vendor_email']):
            print(f"Skipping quotation {row['id']}: Vendor email not found for vendor_id {row['vendor_id']}.")
            continue
        
        # Skip if not in the pending state we're tracking
        if row['state'] != QUOTATION_PENDING_STATE:
            continue

        # Calculate days since original request
        days_since_created = (current_time - row['created_at']).days

        # Check if overdue (>= DAYS_OVERDUE_THRESHOLD days)
        if days_since_created >= DAYS_OVERDUE_THRESHOLD:
            if pd.isna(row['last_reminder_sent_at']): 
                print(f"Quotation {row['id']} (Indent: {row['indent_id']}) is overdue ({days_since_created} days). No reminder sent yet. Adding to reminders list.")
                overdue_quotes_to_process.append(row)
            else:
                days_since_last_reminder = (current_time - row['last_reminder_sent_at']).days
                if days_since_last_reminder >= DAYS_BETWEEN_REMINDERS:
                    print(f"Quotation {row['id']} (Indent: {row['indent_id']}) is overdue ({days_since_created} days) and reminder threshold met ({days_since_last_reminder} days since last). Adding to reminders list.")
                    overdue_quotes_to_process.append(row)
                


    print(f"\nFound {len(overdue_quotes_to_process)} quotations requiring follow-up.")

    # Generate and Send Emails
    if not overdue_quotes_to_process:
        print("No emails to send today based on current data and thresholds.")
    else:
        for quote_data in overdue_quotes_to_process:
            vendor_name = quote_data['vendor_name']
            vendor_email = quote_data['vendor_email']
            indent_id = quote_data['indent_id']
            quotation_id = quote_data['id']
            items_requested = quote_data['items_requested']
            original_request_date = quote_data['created_at'].strftime('%Y-%m-%d')
            form_link = f"https://yourcompany.com/quotes/form?id={quote_data['uuid']}"

            print(f"\n--- Processing Reminder for Quotation ID: {quotation_id} (Indent: {indent_id}) ---")
            print(f"Generating email for {vendor_name} ({vendor_email})...")

            subject, body = generate_follow_up_email(
                vendor_name,
                indent_id,
                items_requested,
                original_request_date,
                form_link
            )

            print(f"Generated Subject: {subject}")
            print(f"Generated Body (first 200 chars):\n{body[:200]}...")
            if len(body) > 200:
                print("...")

            
            email_sent_successfully = send_email_smtp(vendor_email, subject, body)

            if email_sent_successfully:
                current_row_index = quotations_df[quotations_df['id'] == quotation_id].index[0]
                quotations_df.loc[current_row_index, 'last_reminder_sent_at'] = current_time
                print(f"LOG: Updated last_reminder_sent_at for quotation ID {quotation_id} to {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                print(f"WARNING: Email for quotation ID {quotation_id} failed to send. last_reminder_sent_at NOT updated.")

    # Save Updated Data Back to CSV
    # Fill NaT values with empty string before saving to CSV
    quotations_df['created_at'] = quotations_df['created_at'].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
    quotations_df['updated_at'] = quotations_df['updated_at'].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
    quotations_df['last_reminder_sent_at'] = quotations_df['last_reminder_sent_at'].dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')

    quotations_df.to_csv('quotations.csv', index=False)
    print("\n--- Updated 'quotations.csv' with latest reminder timestamps ---")
    print("--- Daily Follow-Up Automation Finished ---")

if __name__ == "__main__":
    run_daily_follow_up_automation()