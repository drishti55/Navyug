from modules.utils import _alert_human_review 

def handle_acknowledgment(original_from, email_subject, original_message_id, original_references, 
                          send_email_func, quoted_message_for_reply):
    """
    Handles the ACKNOWLEDGMENT intent.
    Sends a polite auto-reply and does not typically trigger human review or state changes.
    """
    print(f"Action: Email from {original_from} classified as 'ACKNOWLEDGMENT'. Sending a polite reply.")
    
    update_required = False
    alert_human = False
    new_state = None 
    alert_subject = None
    alert_body = None

    auto_reply_subject = email_subject 
    auto_reply_body = f"""
Dear Vendor,

Thank you for your message. We are glad to hear from you and appreciate your communication.

Best regards,

Navyug Infosolutions Team
{quoted_message_for_reply}
"""
    print(f"DEBUG: Attempting to send auto-reply for ACKNOWLEDGMENT to {original_from} with threading headers.")
    send_email_func(original_from, auto_reply_subject, auto_reply_body, original_message_id, original_references)
    

    return None, update_required, alert_human, new_state, alert_subject, alert_body

