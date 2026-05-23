import pandas as pd
from datetime import datetime, timedelta
import uuid as uuid_lib

def create_initial_csv_files():
    """
    Generates initial quotations.csv and vendor_contacts.csv files
    with correct structure and data types for testing.
    """
    print("--- Generating initial CSV files... ---")

    # --- 1. Generate quotations_df ---
    # Adjusted base_date to ensure some quotes are overdue based on current time (June 24, 2025)
    base_date_for_overdue_test = datetime(2025, 6, 10, 10, 0, 0) 

    quotations_data_rows = [
        # id, indent_id, vendor_id, state, quotation_number, form_submission_counter, created_at, updated_at, uuid, last_reminder_sent_at, items_requested, needs_human_review, expected_submission_date
        # Note: state 1 = pending, 2 = filled, 3 = resubmitted, 4 = needs_review, 5 = out_of_office, 6 = cannot_quote
        
        # Overdue, no reminder sent yet (created_at: June 10)
        (101, 1, 'V001', 1, 'QN2506100001', 0, base_date_for_overdue_test, base_date_for_overdue_test, str(uuid_lib.uuid4()), None, "10 units of Widget X, 5 units of Gadget B", False, None),
        
        # Overdue, reminder sent a few days ago (created_at: June 11, last_reminder_sent_at: June 16)
        # This one should trigger a new reminder if DAYS_BETWEEN_REMINDERS is small enough (e.g., 3 days)
        (102, 2, 'V002', 1, 'QN25061100002', 0, base_date_for_overdue_test + timedelta(days=1), base_date_for_overdue_test + timedelta(days=1), str(uuid_lib.uuid4()), datetime(2025, 6, 16, 11, 0, 0), "20 units of Alpha Component", False, None), 
        
        # Already filled, should be skipped
        (103, 3, 'V003', 2, 'QN25061100003', 1, base_date_for_overdue_test + timedelta(days=2), base_date_for_overdue_test + timedelta(days=2), str(uuid_lib.uuid4()), datetime(2025, 6, 16, 11, 0, 0), "5 units of Beta Module", False, None), 
        
        # Overdue, no reminder sent (created_at: June 7)
        (104, 4, 'V004', 1, 'QN25060700004', 0, base_date_for_overdue_test - timedelta(days=3), base_date_for_overdue_test - timedelta(days=3), str(uuid_lib.uuid4()), None, "1 unit of Delta Device", False, None),
        
        # Overdue, reminder sent (created_at: June 5, last_reminder_sent_at: June 15)
        # This should trigger a reminder if today (June 24) is > 3 days past June 15.
        (105, 5, 'V001', 1, 'QN25060500005', 0, base_date_for_overdue_test - timedelta(days=5), base_date_for_overdue_test - timedelta(days=5), str(uuid_lib.uuid4()), datetime(2025, 6, 15, 10, 0, 0), "15 units of Gamma Material", False, None), 
        
        # Not yet overdue (created_at: June 23, 2025, which is yesterday relative to June 24)
        (106, 6, 'V005', 1, 'QN25062300006', 0, datetime(2025, 6, 23, 9, 0, 0), datetime(2025, 6, 23, 9, 0, 0), str(uuid_lib.uuid4()), None, "30 units of Epsilon Wire", False, None), 
        
        # Quote that needs human review initially (for testing the state flow)
        (107, 7, 'V001', 4, 'QN25061800007', 0, datetime(2025, 6, 18, 14, 0, 0), datetime(2025, 6, 18, 14, 0, 0), str(uuid_lib.uuid4()), None, "Urgent part Z", True, None),
        
        # Quote with an expected submission date (for testing DATE_PROVIDED intent)
        # Note: datetime.date objects for expected_submission_date are fine for initial DataFrame creation
        (108, 8, 'V002', 1, 'QN25061900008', 0, datetime(2025, 6, 19, 10, 0, 0), datetime(2025, 6, 19, 10, 0, 0), str(uuid_lib.uuid4()), None, "Services for Project A", False, datetime(2025, 7, 5).date()),
    
    ]

    quotations_columns = [
        'id', 'indent_id', 'vendor_id', 'state', 'quotation_number',
        'form_submission_counter', 'created_at', 'updated_at', 'uuid',
        'last_reminder_sent_at', 'items_requested', 'needs_human_review', 'expected_submission_date'
    ]

    quotations_df = pd.DataFrame(quotations_data_rows, columns=quotations_columns)

    # Convert 'created_at' and 'updated_at' to datetime and then format to string
    quotations_df['created_at'] = pd.to_datetime(quotations_df['created_at']).dt.strftime('%Y-%m-%d %H:%M:%S')
    quotations_df['updated_at'] = pd.to_datetime(quotations_df['updated_at']).dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # Convert 'last_reminder_sent_at' to datetime, then format to string and fill NaT values
    quotations_df['last_reminder_sent_at'] = pd.to_datetime(quotations_df['last_reminder_sent_at'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S').fillna('')
    
    # --- THIS IS THE CRITICAL FIX FOR 'expected_submission_date' ---
    # First, convert the column to datetime objects (any None will become NaT)
    # Then, use .dt accessor to format, and fill any NaT with an empty string
    quotations_df['expected_submission_date'] = pd.to_datetime(quotations_df['expected_submission_date'], errors='coerce').dt.strftime('%Y-%m-%d').fillna('')

    quotations_df.to_csv('quotations.csv', index=False)
    print("Created 'quotations.csv'")

    # --- 2. Generate vendor_contacts_df ---
    vendor_data = {
        'vendor_id': ['V001', 'V002', 'V003', 'V004', 'V005'],
        'vendor_name': ['Global Supplies Inc.', 'Tech Solutions Ltd.', 'Innovate Materials', 'Precision Parts Co.', 'Unified Logistics'],
        'vendor_email': ['kimjungkook260@gmail.com', 'kimjungkook260@gmail.com', 'kimjungkook260@gmail.com', 'kimjungkook260@gmail.com', 'kimjungkook260@gmail.com']
    }
    vendor_contacts_df = pd.DataFrame(vendor_data)
    vendor_contacts_df.to_csv('vendor_contacts.csv', index=False)
    print("Created 'vendor_contacts.csv'")

    print("--- CSV file generation complete. ---")

if __name__ == "__main__":
    create_initial_csv_files()