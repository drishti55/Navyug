import pandas as pd
from datetime import datetime

import dspy

from modules.utils import STATE_PENDING, STATE_NEEDS_HUMAN_REVIEW


def generate_follow_up_email_content(vendor_name, indent_id, items_requested, original_request_date, form_link, quotation_uuid):
    """
    Generates the subject and body for a follow-up email using the LLM.
    This function relies on dspy.settings.lm being configured globally (in main.py).
    """
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
    8. Include a polite closing from "Navyug Infosolutions Team".

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


def process_outgoing_follow_ups(quotations_df, merged_df, current_time, 
                                  DAYS_OVERDUE_THRESHOLD, DAYS_BETWEEN_REMINDERS, 
                                  send_email_func, HUMAN_REVIEW_EMAIL):
    """
    Identifies overdue quotations and sends automated follow-up emails.
    Updates the 'last_reminder_sent_at' column in the DataFrame.
    """
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
            send_email_func(HUMAN_REVIEW_EMAIL, f"ACTION REQUIRED: Missing Vendor Email for Quote ID {row['id']}",
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
            items_requested_for_email = quote_data['items_requested'] 
            original_request_date = quote_data['created_at'].strftime('%Y-%m-%d')
            quotation_uuid = quote_data['uuid']
            form_link = f"https://yourcompany.com/quotes/form?id={quotation_uuid}"

            print(f"\n--- Sending Reminder for Quotation ID: {quotation_id} (Indent: {indent_id}) ---")
            print(f"Generating email for {vendor_name} ({vendor_email})...")

            subject, body = generate_follow_up_email_content(
                vendor_name,
                indent_id,
                items_requested_for_email, 
                original_request_date,
                form_link,
                quotation_uuid
            )

            print(f"Generated Subject: {subject}")
            print(f"Generated Body (first 200 chars):\\n{body[:200]}...")

            email_sent_successfully = send_email_func(vendor_email, subject, body)

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
                send_email_func(HUMAN_REVIEW_EMAIL, f"ACTION REQUIRED: Failed to Send Reminder for Quote ID {quotation_id}",
                           f"The system failed to send a reminder email to {vendor_email} for Quotation ID {quotation_id} (Indent: {indent_id}). Please review.\n\nSubject: {subject}\nBody:\n{body}")
    
    return quotations_df
