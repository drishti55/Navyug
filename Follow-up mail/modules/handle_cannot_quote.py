import pandas as pd
from modules.utils import _alert_human_review, STATE_CANNOT_QUOTE 

def handle_cannot_quote(quotations_df, quotation_row_index, linked_quotation_id, relevant_indent_id, 
                        original_from, email_subject, original_message_id, original_references, 
                        send_email_func, HUMAN_REVIEW_EMAIL):
    """Handles the CANNOT_QUOTE intent."""
    update_required = False
    alert_human = False
    new_state = None
    alert_subject = None
    alert_body = None

    if quotation_row_index is not None:
        new_state = STATE_CANNOT_QUOTE
        update_required = True
        print(f"Action: Quotation {linked_quotation_id} marked as CANNOT_QUOTE.")
        auto_reply_subject = email_subject
        auto_reply_body = f"""
Dear Vendor,

Thank you for letting us know that you are unable to provide a quotation for Indent ID {relevant_indent_id}. We appreciate you taking the time to respond.

Best regards,

Navyug Infosolutions Team
"""
        print(f"DEBUG: Attempting to send auto-reply for CANNOT_QUOTE to {original_from} with threading headers.")
        send_email_func(original_from, auto_reply_subject, auto_reply_body, original_message_id, original_references)
    else:
        print(f"Action: CANNOT_QUOTE email from {original_from}. No linked quotation. Flagging for human review.")
        alert_human = True
        alert_subject = f"ACTION REQUIRED: 'Cannot Quote' received, No Link - From: {original_from}"
        alert_body = f"A 'Cannot Quote' email was received from {original_from}, but no linked quotation ID. Please review."

    return quotations_df, update_required, alert_human, new_state, alert_subject, alert_body
