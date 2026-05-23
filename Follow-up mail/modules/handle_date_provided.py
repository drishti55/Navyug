import pandas as pd
from modules.utils import _alert_human_review, STATE_PENDING, STATE_NEEDS_HUMAN_REVIEW 

def handle_date_provided(quotations_df, quotation_row_index, linked_quotation_id, relevant_indent_id, 
                         original_from, email_subject, original_message_id, original_references, 
                         send_email_func, calendar_service, extracted_date, items_requested, 
                         quoted_message_for_reply):
    """Handles the DATE_PROVIDED intent."""
    update_required = False
    alert_human = False
    new_state = None
    alert_subject = None
    alert_body = None

    if quotation_row_index is not None and extracted_date:
        quotations_df.loc[quotation_row_index, 'expected_submission_date'] = extracted_date.strftime('%Y-%m-%d')
        new_state = STATE_PENDING 
        update_required = True
        print(f"Action: Quotation {linked_quotation_id} updated with expected submission date: {extracted_date.strftime('%Y-%m-%d')}.")
        
        if calendar_service: 
            event = {
                'summary': f'Quotation Due: Indent ID {relevant_indent_id}',
                'description': (
                    f'Expected submission from {original_from} for: {items_requested}. ' 
                    f'Quotation ID: {linked_quotation_id}. '
                    f'Original Email Subject: {email_subject}.'
                ),
                'start': {
                    'date': extracted_date.strftime('%Y-%m-%d'),
                    'timeZone': 'Asia/Kolkata', 
                },
                'end': {
                    'date': extracted_date.strftime('%Y-%m-%d'),
                    'timeZone': 'Asia/Kolkata',
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60}, 
                        {'method': 'popup', 'minutes': 60},     
                    ],
                },
            }
            try:
                created_event = calendar_service.events().insert(calendarId='primary', body=event).execute()
                print(f'SUCCESS: Google Calendar event created: {created_event.get("htmlLink")}')
            except Exception as e:
                print(f'ERROR: An unexpected error occurred while creating calendar event: {e}')
        else:
            print("INFO: Google Calendar service not initialized, skipping event creation.")

        auto_reply_subject = email_subject
        auto_reply_body = f"""
Dear Vendor,

Thank you for your update regarding quotation for Indent ID {relevant_indent_id}. We have noted your expected submission date as {extracted_date.strftime('%Y-%m-%d')}. We will remind you closer to that date if needed.

We appreciate your timely communication.

Best regards,

Navyug Infosolutions Team
{quoted_message_for_reply}
""" 
        print(f"DEBUG: Attempting to send auto-reply for DATE_PROVIDED to {original_from} with threading headers.")
        send_email_func(original_from, auto_reply_subject, auto_reply_body, original_message_id, original_references)

    elif quotation_row_index is not None: 
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

Thank you for your message regarding the expected submission date for Indent ID {relevant_indent_id}. We were unable to automatically process the date provided and will review your message manually. We will be in touch if we require further clarification.

Best regards,

Navyug Infosolutions Team
{quoted_message_for_reply}
"""
        print(f"DEBUG: Attempting to send auto-reply for DATE_PROVIDED (unparsed) to {original_from} with threading headers.")
        send_email_func(original_from, auto_reply_subject, auto_reply_body, original_message_id, original_references)

    else: 
        print(f"Action: DATE_PROVIDED for {original_from} but no link. Needs human to confirm/extract date AND link to a quote.")
        alert_human = True
        alert_subject = f"ACTION REQUIRED: Date Provided (Unlinked) - From: {original_from}"
        alert_body = f"A supplier has indicated a submission date ({original_from}) but no linked quotation ID could be found." 
    
    return quotations_df, update_required, alert_human, new_state, alert_subject, alert_body
