STATE_PENDING = 1
STATE_FILLED = 2
STATE_RESUBMITTED = 3
STATE_NEEDS_HUMAN_REVIEW = 4
STATE_OUT_OF_OFFICE = 5
STATE_CANNOT_QUOTE = 6

def _alert_human_review(send_email_func, human_review_email, alert_subject, alert_body, 
                        original_from, email_subject, original_date, email_body, 
                        linked_quotation_id, relevant_indent_id, conversation_summary_text):
    """
    Helper function to send an alert email to the human review team.
    This function is designed to be called by various intent handlers when human intervention is needed.
    """
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
    print(f"DEBUG: Sending human review alert to {human_review_email} for subject: {alert_subject[:70]}...")
    send_email_func(human_review_email, alert_subject, final_alert_body)