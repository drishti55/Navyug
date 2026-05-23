import pandas as pd
from modules.utils import _alert_human_review, STATE_OUT_OF_OFFICE 

def handle_out_of_office(quotations_df, quotation_row_index, linked_quotation_id, relevant_indent_id, 
                        original_from, email_subject, original_message_id, original_references, 
                        send_email_func, HUMAN_REVIEW_EMAIL):
    """Handles the OUT_OF_OFFICE intent."""
    update_required = False
    alert_human = False
    new_state = None
    alert_subject = None
    alert_body = None

    if quotation_row_index is not None:
        new_state = STATE_OUT_OF_OFFICE
        update_required = True
        print(f"Action: Quotation {linked_quotation_id} marked as OUT_OF_OFFICE.")
        auto_reply_subject = email_subject
        auto_reply_body = f"""
Dear Vendor,

Thank you for your out-of-office reply. We have noted your return date and will be waiting for your quotation for Indent ID {relevant_indent_id} upon your return.

Best regards,

Navyug Infosolutions Team
""" 
        print(f"DEBUG: Attempting to send auto-reply for OUT_OF_OFFICE to {original_from} with threading headers.")
        send_email_func(original_from, auto_reply_subject, auto_reply_body, original_message_id, original_references)
    else:
        print(f"Action: OUT_OF_OFFICE email from {original_from}. No linked quotation, so no DB update. Informing human.")
        alert_human = True
        alert_subject = f"INFO: Out of Office Reply (Unlinked) - From: {original_from}"
        alert_body = f"An Out of Office reply was received from {original_from}. No linked quotation ID. For your information."

    return quotations_df, update_required, alert_human, new_state, alert_subject, alert_body
