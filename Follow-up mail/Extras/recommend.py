import pandas as pd
import os


dummy_quotations_csv_content = """id,uuid,indent_id,vendor_id,items_requested,created_at,updated_at,last_reminder_sent_at,expected_submission_date,state,needs_human_review
159,a1b2c3d4-e5f6-7890-1234-567890abcdef,150,VNDR-101,"Item 200",2025-06-20 10:00:00,2025-06-20 10:00:00,,2025-06-25,2,False
160,b2c3d4e5-f6a7-8901-2345-67890abcdef0,151,VNDR-102,"Item 93, Item 83",2025-06-20 11:00:00,2025-06-20 11:00:00,,2025-06-26,2,False
161,c3d4e5f6-a7b8-9012-3456-7890abcdef01,151,VNDR-103,"Item 93, Item 83",2025-06-20 12:00:00,2025-06-20 12:00:00,,2025-06-27,2,False
162,d4e5f6a7-b8c9-0123-4567-890abcdef012,151,VNDR-104,"Item 93, Item 83",2025-06-20 13:00:00,2025-06-20 13:00:00,,2025-06-28,2,False
163,e5f6a7b8-c9d0-1234-5678-90abcdef0123,152,VNDR-105,"Item 63",2025-06-20 14:00:00,2025-06-20 14:00:00,,2025-06-29,2,False
"""


dummy_quotation_items_csv_content = """id,quotation_id,indent_item_id,item_id,unit_price,freight_price,total_price,delivery_date,payment_term,state,created_at,updated_at
206,159,193,200,10.0,20.0,120.0,2025-07-01,Net 30,2,2025-06-26 06:37:39.96148,2025-06-26 06:37:39.96148
207,160,194,93,12.0,15.0,75.0,2025-07-05,Net 30,2,2025-06-30 09:59:15.311556,2025-06-30 09:59:15.311556
208,160,195,83,25.0,10.0,60.0,2025-07-05,Net 30,2,2025-06-30 09:59:15.315612,2025-06-30 09:59:15.315612
209,161,194,93,11.0,18.0,73.0,2025-07-07,Net 45,2,2025-06-30 09:59:15.381073,2025-06-30 09:59:15.381073
210,161,195,83,27.0,12.0,66.0,2025-07-07,Net 45,2,2025-06-30 09:59:15.416488,2025-06-30 09:59:15.416488
211,162,194,93,13.0,10.0,75.0,2025-07-03,Net 60,2,2025-06-30 10:00:00.000000,2025-06-30 10:00:00.000000
212,162,195,83,24.0,8.0,56.0,2025-07-03,Net 60,2,2025-06-30 10:00:00.000000,2025-06-30 10:00:00.000000
"""

dummy_indent_items_csv_content = """indent_item_id,indent_id,item_id,quantity_requested
193,150,200,10
194,151,93,5
195,151,83,2
196,152,63,8
197,153,72,12
"""

dummy_indents_csv_content = """id,description,request_date
150,Transformer Components,2025-06-15
151,Electronic Parts Order,2025-06-18
152,Heavy Machinery Spare,2025-06-20
153,Software Licenses,2025-06-22
"""

dummy_items_csv_content = """id,name,description,unit
200,Capacitor XYZ,High-voltage capacitor,pcs
93,Microcontroller ABC,Advanced MCU,pcs
83,Resistor 1k Ohm,Standard 1k Ohm resistor,pcs
63,Bearing Set DFG,Industrial bearing set,sets
72,Power Supply Unit,24V 10A PSU,units
"""

dummy_vendor_contacts_csv_content = """vendor_id,vendor_name,vendor_email,phone
VNDR-101,Tech Solutions Inc.,contact@techsolutions.com,+1-555-123-4567
VNDR-102,Global Parts Co.,sales@globalparts.com,+44-20-7946-0123
VNDR-103,Cable Supply Ltd.,info@cablesupply.co.uk,+81-3-xxxx-xxxx
VNDR-104,Industrial Pumps Inc.,support@industrialpumps.com,+61-2-xxxx-xxxx
VNDR-105,Consulting Services LLC,inquiry@consultingservices.com,+1-800-555-TECH
"""

def create_dummy_csv_files():
    with open('quotations.csv', 'w') as f:
        f.write(dummy_quotations_csv_content)
    with open('quotation_items.csv', 'w') as f:
        f.write(dummy_quotation_items_csv_content)
    with open('indent_items.csv', 'w') as f:
        f.write(dummy_indent_items_csv_content)
    with open('indents.csv', 'w') as f:
        f.write(dummy_indents_csv_content)
    with open('items.csv', 'w') as f:
        f.write(dummy_items_csv_content)
    with open('vendor_contacts.csv', 'w') as f:
        f.write(dummy_vendor_contacts_csv_content)
    print("Dummy CSV files created for demonstration.")

create_dummy_csv_files()

STATE_PENDING = 1
STATE_FILLED = 2 
def recommend_best_quotation():
    print("--- Starting Quotation Recommendation Model ---")

    try:
        quotations_df = pd.read_csv('quotations.csv')
        quotation_items_df = pd.read_csv('quotation_items.csv')
        indent_items_df = pd.read_csv('indent_items.csv')
        indents_df = pd.read_csv('indents.csv') 
        vendor_contacts_df = pd.read_csv('vendor_contacts.csv')
    except FileNotFoundError as e:
        print(f"ERROR: Missing CSV file. Please ensure all dummy CSVs are created or real CSVs exist. Detail: {e}")
        return


    submitted_quotations_df = quotations_df[quotations_df['state'] == STATE_FILLED].copy()
    if submitted_quotations_df.empty:
        print("No filled (submitted) quotations found for analysis. Cannot make recommendations.")
        return

    merged_items_df = pd.merge(
        quotation_items_df,
        indent_items_df[['indent_item_id', 'quantity_requested']],
        on='indent_item_id',
        how='left'
    )

    merged_items_df['calculated_item_total'] = merged_items_df['total_price'].fillna(
        merged_items_df['unit_price'] * merged_items_df['quantity_requested'] + merged_items_df['freight_price'].fillna(0) # Add freight if available, default to 0
    )
    
    merged_items_df.dropna(subset=['calculated_item_total'], inplace=True)
    
    if merged_items_df.empty:
        print("No valid price data found in quotation_items after processing. Cannot recommend.")
        return

    quotation_total_costs = merged_items_df.groupby('quotation_id')['calculated_item_total'].sum().reset_index()
    quotation_total_costs.rename(columns={'calculated_item_total': 'overall_quotation_cost'}, inplace=True)

    final_quotes_df = pd.merge(
        submitted_quotations_df,
        quotation_total_costs,
        left_on='id',         
        right_on='quotation_id',
        how='inner'
    )

    if final_quotes_df.empty:
        print("No submitted quotations with calculable costs found for comparison. Cannot recommend.")
        return

    final_quotes_df = pd.merge(
        final_quotes_df,
        vendor_contacts_df[['vendor_id', 'vendor_name']],
        on='vendor_id',
        how='left'
    )
    
    print("\n--- Identifying Best Quotation (Lowest Price) for each Indent ---")
    recommendations = {}

    for indent_id, group in final_quotes_df.groupby('indent_id'):
        if len(group) > 1:
            best_quote_for_indent = group.loc[group['overall_quotation_cost'].idxmin()]
            recommendations[indent_id] = best_quote_for_indent
            print(f"\nIndent ID: {indent_id}")
            print(f"  RECOMMENDED QUOTATION:")
            print(f"    Quotation ID: {best_quote_for_indent['id']}")
            print(f"    Vendor: {best_quote_for_indent['vendor_name']} (ID: {best_quote_for_indent['vendor_id']})")
            print(f"    Total Quoted Price: ₹{best_quote_for_indent['overall_quotation_cost']:.2f}")
            print(f"    Items Requested (from quotation): {best_quote_for_indent['items_requested']}")
            
            print("  --- Other competing quotes received for this Indent: ---")
            for idx, row in group.iterrows():
                if row['id'] != best_quote_for_indent['id']:
                    print(f"    - Quote ID {row['id']} from {row['vendor_name']}: ₹{row['overall_quotation_cost']:.2f}")
            print("  --------------------------------------------------------")

        elif len(group) == 1:
            single_quote = group.iloc[0]
            recommendations[indent_id] = single_quote
            print(f"\nIndent ID: {indent_id}")
            print(f"  Only one submitted quotation received for this indent.")
            print(f"  Quotation ID: {single_quote['id']}")
            print(f"  Vendor: {single_quote['vendor_name']} (ID: {single_quote['vendor_id']})")
            print(f"  Total Quoted Price: ₹{single_quote['overall_quotation_cost']:.2f}")
            print(f"  Items Requested (from quotation): {single_quote['items_requested']}")
        else:
            print(f"\nIndent ID: {indent_id}: No submitted quotations to compare or no valid cost data.")

    if not recommendations:
        print("\nNo recommendations could be made based on the available submitted quotations with valid costs.")
    
    print("\n--- Quotation Recommendation Model Finished ---")
    return recommendations

if __name__ == "__main__":
    recommend_best_quotation()

