import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import uuid as uuid_lib
import os

print("--- Starting PostgreSQL Database Setup ---")

# --- 0. Database Configuration from Environment Variables ---
DB_HOST = os.getenv("PG_DB_HOST", "localhost")
DB_NAME = os.getenv("PG_DB_NAME", "procurement_db")
DB_USER = os.getenv("PG_DB_USER", "postgres")
DB_PASSWORD = os.getenv("PG_DB_PASSWORD", "password") # Replace with your PG password
DB_PORT = os.getenv("PG_DB_PORT", "5432")

# Basic validation
if not all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT]):
    print("ERROR: One or more PostgreSQL environment variables (PG_DB_HOST, PG_DB_NAME, PG_DB_USER, PG_DB_PASSWORD, PG_DB_PORT) are NOT set.")
    print("Please ensure they are configured correctly.")
    exit(1) # Exit the script if configuration is incomplete

def create_and_populate_db():
    conn = None
    try:
        print(f"DEBUG: Attempting to connect to PostgreSQL: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
        # Establish a connection
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT
        )
        cur = conn.cursor()
        print("DEBUG: Connected to PostgreSQL successfully.")

        # --- 1. Define Table Schemas and Drop/Create Tables ---
        print("DEBUG: Dropping existing tables if they exist...")
        cur.execute("DROP TABLE IF EXISTS quotations;")
        cur.execute("DROP TABLE IF EXISTS vendor_contacts;")
        conn.commit()
        print("DEBUG: Old tables dropped.")

        print("DEBUG: Creating new tables...")
        create_quotations_table_sql = """
        CREATE TABLE quotations (
            id SERIAL PRIMARY KEY,
            indent_id INTEGER NOT NULL,
            vendor_id VARCHAR(50) NOT NULL,
            state INTEGER NOT NULL,
            quotation_number VARCHAR(100),
            form_submission_counter INTEGER DEFAULT 0,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            uuid VARCHAR(36) UNIQUE NOT NULL,
            last_reminder_sent_at TIMESTAMP,
            items_requested TEXT,
            needs_human_review BOOLEAN DEFAULT FALSE,
            expected_submission_date DATE
        );
        """
        create_vendor_contacts_table_sql = """
        CREATE TABLE vendor_contacts (
            vendor_id VARCHAR(50) PRIMARY KEY,
            vendor_name VARCHAR(255) NOT NULL,
            vendor_email VARCHAR(255) NOT NULL
        );
        """
        cur.execute(create_quotations_table_sql)
        cur.execute(create_vendor_contacts_table_sql)
        conn.commit()
        print("DEBUG: Tables created successfully.")

        # --- 2. Generate and Insert Sample Data ---
        print("DEBUG: Generating sample data...")
        # Use a fixed past date for testing overdue logic. Current date is Wednesday, June 25, 2025.
        base_date_for_overdue_test = datetime(2025, 6, 10, 10, 0, 0) 

        quotations_data_rows = [
            (101, 1, 'V001', 1, 'QN2506100001', 0, base_date_for_overdue_test, base_date_for_overdue_test, str(uuid_lib.uuid4()), None, "10 units of Widget X, 5 units of Gadget B", False, None),
            (102, 2, 'V002', 1, 'QN25061100002', 0, base_date_for_overdue_test + timedelta(days=1), base_date_for_overdue_test + timedelta(days=1), str(uuid_lib.uuid4()), datetime(2025, 6, 16, 11, 0, 0), "20 units of Alpha Component", False, None), 
            (103, 3, 'V003', 2, 'QN25061100003', 1, base_date_for_overdue_test + timedelta(days=2), base_date_for_overdue_test + timedelta(days=2), str(uuid_lib.uuid4()), datetime(2025, 6, 16, 11, 0, 0), "5 units of Beta Module", False, None), 
            (104, 4, 'V004', 1, 'QN25060700004', 0, base_date_for_overdue_test - timedelta(days=3), base_date_for_overdue_test - timedelta(days=3), str(uuid_lib.uuid4()), None, "1 unit of Delta Device", False, None), 
            (105, 5, 'V001', 1, 'QN25060500005', 0, base_date_for_overdue_test - timedelta(days=5), base_date_for_overdue_test - timedelta(days=5), str(uuid_lib.uuid4()), datetime(2025, 6, 15, 10, 0, 0), "15 units of Gamma Material", False, None), 
            (106, 6, 'V005', 1, 'QN25062300006', 0, datetime(2025, 6, 23, 9, 0, 0), datetime(2025, 6, 23, 9, 0, 0), str(uuid_lib.uuid4()), None, "30 units of Epsilon Wire", False, None), 
            (107, 7, 'V001', 4, 'QN25061800007', 0, datetime(2025, 6, 18, 14, 0, 0), datetime(2025, 6, 18, 14, 0, 0), str(uuid_lib.uuid4()), None, "Urgent part Z", True, None),
            (108, 8, 'V002', 1, 'QN25061900008', 0, datetime(2025, 6, 19, 10, 0, 0), datetime(2025, 6, 19, 10, 0, 0), str(uuid_lib.uuid4()), None, "Services for Project A", False, datetime(2025, 7, 5).date()),
        ]

        # Convert to DataFrame for easy insertion
        quotations_df = pd.DataFrame(quotations_data_rows, columns=[
            'id', 'indent_id', 'vendor_id', 'state', 'quotation_number',
            'form_submission_counter', 'created_at', 'updated_at', 'uuid',
            'last_reminder_sent_at', 'items_requested', 'needs_human_review', 'expected_submission_date'
        ])

        # Insert data using pandas to_sql for simplicity
        # This will create table columns based on DataFrame dtypes if table doesn't exist (but we created them explicitly)
        # We handle NaT/None values by letting pandas handle them during SQL insertion; NULL will be inserted.
        quotations_df.to_sql('quotations', conn, if_exists='append', index=False, dtype={
            'created_at': psycopg2.TIMESTAMP,
            'updated_at': psycopg2.TIMESTAMP,
            'last_reminder_sent_at': psycopg2.TIMESTAMP,
            'expected_submission_date': psycopg2.DATE,
            'needs_human_review': psycopg2.BOOLEAN
        })
        print("DEBUG: Sample quotations inserted.")

        vendor_data = {
            'vendor_id': ['V001', 'V002', 'V003', 'V004', 'V005'],
            'vendor_name': ['Global Supplies Inc.', 'Tech Solutions Ltd.', 'Innovate Materials', 'Precision Parts Co.', 'Unified Logistics'],
            'vendor_email': ['drishti.raiswal@navyuginfo.com', 'drishti.raiswal@navyuginfo.com', 'drishti.raiswal@navyuginfo.com', 'drishti.raiswal@navyuginfo.com', 'drishti.raiswal@navyuginfo.com']
        }
        vendor_contacts_df = pd.DataFrame(vendor_data)

        vendor_contacts_df.to_sql('vendor_contacts', conn, if_exists='append', index=False)
        print("DEBUG: Sample vendor contacts inserted.")

        conn.commit()
        print("--- Database setup and population complete. ---")

    except psycopg2.Error as e:
        print(f"CRITICAL ERROR: PostgreSQL database error: {e}")
        if conn:
            conn.rollback() 
    except Exception as e:
        print(f"CRITICAL ERROR: An unexpected error occurred during database setup: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()
            print("DEBUG: PostgreSQL connection closed.")

if __name__ == "__main__":
    create_and_populate_db()


'''
$env:PG_DB_HOST="localhost"
$env:PG_DB_NAME="procurement_db" # Or your database name
$env:PG_DB_USER="postgres"       # Your PostgreSQL username
$env:PG_DB_PASSWORD="your_actual_password" # Your PostgreSQL password
$env:PG_DB_PORT="5432"
'''