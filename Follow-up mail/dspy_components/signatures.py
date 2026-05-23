import dspy
from datetime import datetime, timedelta 
from dateutil import parser 

class EmailIntentExtraction(dspy.Signature):
    """Classify the intent of an incoming supplier email and extract a submission date if applicable.
    The extracted date must be the most likely submission date mentioned in the email, in INSEE-MM-DD format.
    If no clear date is mentioned, or if the intent is not DATE_PROVIDED, set extracted_date to null.
    
    The intent must be one of: QUOTE_SUBMITTED, OUT_OF_OFFICE, CANNOT_QUOTE, DATE_PROVIDED, NEEDS_ASSISTANCE, UNCLEAR_OTHER, ACKNOWLEDGMENT.
    
    Examples:
    Email: Subject: "Quote attached for ID 123", Body: "Here's the final quote. Thanks." -> Intent: QUOTE_SUBMITTED, extracted_date: null
    Email: Subject: "RE: Your Inquiry", Body: "I am out of office until next week." -> Intent: OUT_OF_OFFICE, extracted_date: null
    Email: Subject: "Cannot provide quote for Widget X", Body: "We do not carry these specific parts. Apologies." -> Intent: CANNOT_QUOTE, extracted_date: null
    Email: Subject: "Problem with Form ID: ABCD", Body: "The upload button is not working. I can't attach my quote." -> Intent: NEEDS_ASSISTANCE, extracted_date: null
    Email: Subject: "Question about specifications", Body: "Can you clarify the dimensions for item 5? We need assistance." -> Intent: NEEDS_ASSISTANCE, extracted_date: null
    Email: Subject: "Expected submission date", Body: "We will submit the quote by 2025-07-30." -> Intent: DATE_PROVIDED, extracted_date: 2025-07-30
    Email: Subject: "Thanks for the info", Body: "Noted with thanks." -> Intent: ACKNOWLEDGMENT, extracted_date: null
    Email: Subject: "Free vacation!", Body: "Click here to claim your prize." -> Intent: UNCLEAR_OTHER, extracted_date: null
    Email: Subject: "RE: Indent 123 - Update", Body: "So what happened wass there were 27 items and customer requested 27 but now one is broke so now there are 26 left." -> Intent: NEEDS_ASSISTANCE, extracted_date: null
    Email: Subject: "RE: Your Query", Body: "Thank you for your response." -> Intent: ACKNOWLEDGMENT, extracted_date: null
    Email: Subject: "Quote delivery update", Body: "We will send the quote by July 15th." -> Intent: DATE_PROVIDED, extracted_date: 2025-07-15
    Email: Subject: "Confirming receipt", Body: "Could you please confirm if you received our last email regarding Indent 456?" -> Intent: NEEDS_ASSISTANCE, extracted_date: null
    """
    email_subject: str = dspy.InputField(desc="Subject of the email")
    email_body: str = dspy.InputField(desc="Body of the email")
    
    intent: str = dspy.OutputField(desc="Primary intent of the email.")
    extracted_date: str = dspy.OutputField(desc="Most likely submission date in INSEE-MM-DD format, or null.")

class ConversationSummarization(dspy.Signature):
    """Summarize the provided conversation turns into a concise overview, focusing on the vendor's primary query, problem, or request for assistance. Highlight relevant details like specific issues, items, or dates mentioned in their request.

    Examples:
    Conversation:
    User: Can you clarify the dimensions for item 5? We need assistance.
    Model: Dear Vendor, Thank you for your message... Your query requires human attention...
    Summary: The vendor needs clarification on the dimensions for item 5 of the quotation.

    Conversation:
    User: The file size for attachment is too small on your form. Can't upload our full quote.
    Model: Dear Vendor, Thank you for your message... Your query requires human attention...
    Summary: The vendor is encountering a technical issue where the form's attachment file size limit is too small to upload their full quote.

    Conversation:
    User: We'll submit by 2025-07-15.
    Model: Dear Vendor, Thank you for your update... We have noted your expected submission date...
    Summary: The vendor provided an expected submission date of 2025-07-15.

    Conversation:
    User: Noted with thanks.
    Model: Dear Vendor, Thank you for your message. We are glad to hear from you...
    Summary: The vendor sent a simple acknowledgment of the previous communication.
    """
    conversation_turns: str = dspy.InputField(desc="Concatenated text of conversation turns")
    
    summary: str = dspy.OutputField(desc="A concise summary of the conversation, specifically detailing the vendor's request or problem.")
