import pandas as pd 
from modules.utils import _alert_human_review, STATE_NEEDS_HUMAN_REVIEW 

def handle_needs_assistance_or_unclear_other(quotations_df, quotation_row_index, linked_quotation_id, relevant_indent_id,
                                             original_from, email_subject, original_message_id, original_references, 
                                             send_email_func, intent, quoted_message_for_reply, 
                                             HUMAN_REVIEW_EMAIL):
    """
    Handles NEEDS_ASSISTANCE and UNCLEAR_OTHER intents.
    Flags the quotation for human review and sends an alert.
    """
    print(f"Action: Email from {original_from} classified as '{intent}'. Flagging for human review.")
    
    update_required = False
    alert_human = True
    new_state = None
    alert_subject = None
    alert_body = None

    if quotation_row_index is not None:
        quotations_df.loc[quotation_row_index, 'needs_human_review'] = True
        new_state = STATE_NEEDS_HUMAN_REVIEW 
        update_required = True 
    
    auto_reply_subject = email_subject
    auto_reply_body = f"""
Dear Vendor,

Thank you for your message regarding Indent ID {relevant_indent_id}. Your query requires human attention and has been flagged for our procurement team's review.

We will get back to you as soon as possible.

Best regards,

Navyug Infosolutions Team
{quoted_message_for_reply}
"""
    print(f"DEBUG: Attempting to send auto-reply for '{intent}' to {original_from} with threading headers.")
    send_email_func(original_from, auto_reply_subject, auto_reply_body, original_message_id, original_references)
    
    alert_subject = f"ACTION REQUIRED: Supplier Reply Needs Review - From: {original_from} (Indent: {relevant_indent_id})"
    alert_body = f"The Automated Follow-Up system has received a supplier reply that requires your immediate attention. The AI classified this email as: **{intent}**."

    return quotations_df, update_required, alert_human, new_state, alert_subject, alert_body

