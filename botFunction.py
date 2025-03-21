import json
import re
import threading
import time
from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import schedule
from datetime import datetime

# === Flask App ===
app = Flask(__name__)

# === Twilio Credentials ===
TWILIO_ACCOUNT_SID = "ACb3d9f995c6baa274bf736d2049ab53dd"
TWILIO_AUTH_TOKEN = "993e8c51ba1ad705193a36341b23d706"
TWILIO_PHONE_NUMBER = "whatsapp:+14155238886"  # Twilio Sandbox Number
CONTENT_SID = "HX670412ff7a7dbea9e150e8803b94e495"  # Replace with your Content SID

client_twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# === Google Sheets Integration ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("database.json", scope)
client = gspread.authorize(creds)
sheet = client.open("ExpenseTracker").sheet1

# === Store User Limits ===
user_budget = {}

# Function to extract month from a date string
def get_month(date_str):
    return date_str[:7]  # Format: "YYYY-MM"
# Function to calculate total expenses for the month
def get_total_expenses_for_month(sender, month):
    all_rows = sheet.get_all_values()
    total = sum(
        int(row[2]) for row in all_rows if row[4] == sender and row[1].startswith(month) and row[2].strip() != ""
    )
    return total
# Function to get the user's budget for the month
def get_user_budget(sender, month):
    all_rows = sheet.get_all_values()
    for row in all_rows:
        if row[4] == sender and row[5].startswith(month):  # Budget stored in Column 6
            return int(row[5].split(":")[1])  # Extract budget amount
    return None

# Function to set budget
def set_budget(sender, amount):
    month = datetime.now().strftime("%Y-%m")  # Get current month
    all_rows = sheet.get_all_values()

    for i, row in enumerate(all_rows):
        if row[4] == sender and row[5].startswith(month):  # Budget is stored in Column 6
            sheet.update_cell(i + 1, 6, f"{month}:{amount}")  # Update existing budget
            return f"✅ Updated budget to ₹{amount} for {month}!"

    # If no budget was found, append a new row
    sheet.append_row(["", month, "", "", sender, f"{month}:{amount}"])
    return f"✅ Budget of ₹{amount} set for {month}!"


def get_next_expense_id():
    all_rows = sheet.get_all_values()

    if len(all_rows) <= 1:  # No data except headers
        return 1

    expense_ids = []

    for row in all_rows[1:]:  # Skip the header row
        if row[0].isdigit():  # Ensure the first column contains numeric expense IDs
            expense_ids.append(int(row[0]))

    return max(expense_ids) + 1 if expense_ids else 1  # Return the next available ID


# === Function to Extract Expense Data ===
def parse_expense(msg):
    match = re.search(r'(\d+(?:\.\d{1,2})?)\s*-\s*(.+)', msg, re.IGNORECASE)
    if match:
        amount = match.group(1)
        category = match.group(2).strip()
        return float(amount), category
    return None, None

# === Send Welcome Message with Interactive Buttons but not able to setup due to my free twilio account ===
'''def send_welcome_message(user):
    print(user)
    client_twilio.messages.create(
        from_=TWILIO_PHONE_NUMBER,
        to=user,
        content_sid=CONTENT_SID,
        content_variables=json.dumps({
            #'1': 'User'
        })
    )'''

# === Handle Incoming Messages ===
# State to track user action
user_state = {}
temp_delete_data = {}
temp_modify_data = {}  # Temporary storage for modifying flow  # To store expenses temporarily for deletion flow
# Track the selected expense ID for modification
user_modify_id = {}
updated_count = 0

@app.route("/whatsapp", methods=['POST'])
def whatsapp_bot():
    global updated_count
    incoming_msg = request.form.get('Body').strip()
    print("incoming_msg", incoming_msg)
    sender = request.form.get('From')
    response = MessagingResponse()
    
    # WELCOME MESSAGE HANDLING
    if incoming_msg.lower() in ['hi', 'hello','start','hey']:
        reply = ("👋 Hello Irfu! Welcome to the Expense Tracker.\n"
                 "1️⃣ ➕ Add Expense\n"
                 "2️⃣ ✏️ Modify Expense\n"
                 "3️⃣ ❌ Remove Expense\n"
                 "4️⃣ 📊 Check Status\n"
                 "5️⃣ ❓ Help\n\n"
                 "👉 Type the number to continue.")
        response.message(reply)
    elif incoming_msg.lower().startswith("set budget"):
        match = re.search(r"set budget (\d+)", incoming_msg.lower())
        if match:
            budget_amount = match.group(1)
            response.message(set_budget(sender, budget_amount))
        else:
            response.message("❌ Invalid format! Use: 'Set budget 10000'")
    # ADD EXPENSE FLOW
    elif incoming_msg == '1':
        user_state[sender] = 'adding_expense'  # Track user state
        response.message("📝 Please type the expense in this format:\n'Amount - Category'")

    elif user_state.get(sender) == 'adding_expense':
        if incoming_msg.lower() in ["done", "exit"]:
            user_state[sender] = None
            response.message("✅ You have exited the Add Expense mode.")
        else:
            amount, category = parse_expense(incoming_msg)
            if amount and category:
                updated_count = get_next_expense_id()
                date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                month = get_month(date)
                sheet.append_row([updated_count, date, amount, category, sender])
                total_spent = get_total_expenses_for_month(sender, month)
                budget = get_user_budget(sender, month)  # Save to Google Sheets
                added_message = f"✅ Logged: ₹{amount} on {category} at {date}.\n\n➕ Want to add another expense? Type it in the format: 'Amount - Category'.\nOr type 'done' to exit."
                if budget:
                    if total_spent >= budget:
                        added_message += f"\n❌ *Budget Exceeded!* You've spent ₹{total_spent} out of ₹{budget}!"
                    elif total_spent >= 0.8 * budget:
                        added_message += f"\n⚠️ *Warning:* You've spent ₹{total_spent} out of ₹{budget}. Be mindful!"

                response.message(added_message)
            else:
                response.message("❌ Invalid format! Use: '200 - Groceries'")
        user_state[sender] = None
    elif incoming_msg == '2':
        user_state[sender] = 'waiting_for_modify'
        response.message("✏️ Please type the ID of the expense you'd like to modify or the date (YYYY-MM-DD).")

    elif user_state.get(sender) == 'waiting_for_modify':
        if re.match(r'^\d{4}-\d{2}-\d{2}$', incoming_msg):  # If user gives a date
            date = incoming_msg.strip()
            expenses = [
                row for row in sheet.get_all_values()
                if row[4] == sender and row[1].startswith(date)
            ]
            if expenses:
                summary = f"📅 *Expenses on {date}:*\n"
                temp_modify_data[sender] = expenses  # Store for later use
                for row in expenses:
                    expense_id = row[0]
                    amount = row[2]
                    category = row[3]
                    summary += f"➡️ *ID:* {expense_id} | ₹{amount} on {category}\n"
                summary += "\n✏️ Please type the ID of the expense you'd like to modify."
            else:
                summary = f"❌ No expenses found on {date}."
            response.message(summary)
        
        elif incoming_msg.isdigit():  # If user gives an ID
            print("entered id")
            expense_id = incoming_msg.strip()

            if sender in temp_modify_data: 
                print("entered id in temp_modify_data") # ✅ If user first entered a date
                matching_expense = [row for row in temp_modify_data[sender] if row[0] == expense_id]
            else: 
                print("entered id directly") # ✅ If user DID NOT enter a date first
                all_expenses = [row for row in sheet.get_all_values() if row[4] == sender]
                matching_expense = [row for row in all_expenses if row[0] == expense_id]

            if matching_expense:
                print("entered id in matching_expense")
                user_state[sender] = 'modifying_expense'
                user_modify_id[sender] = expense_id
                response.message("📝 Please type the new expense in this format:\n'Amount - Category'")
            else:
                response.message(f"❌ No expense found with ID {expense_id}.")


    elif user_state.get(sender) == 'modifying_expense':
        print("entered modifying expense")
        amount, category = parse_expense(incoming_msg)
        if amount and category:
            print("entered amount and category")
            expense_id = user_modify_id[sender]
            all_rows = sheet.get_all_values()

            # Update the matching row in the sheet
            for i, row in enumerate(all_rows):
                if row[0] == expense_id and row[4] == sender:
                    sheet.update_cell(i + 1, 3, amount)  # Update amount
                    sheet.update_cell(i + 1, 4, category)  # Update category
                    break

            response.message(f"✅ Expense with ID {expense_id} has been updated to ₹{amount} on {category}.\n\n"
                             "🛑 You have exited *modifying mode*.\n"
                             " You can now start a new action!")
            print("expense updated")
            # Clean up state
            user_state[sender] = None
            user_modify_id[sender] = None
            temp_modify_data[sender] = None
        else:
            response.message("❌ Invalid format! Please use: 'Amount - Category'")

    # DELETE EXPENSE FLOW
    elif incoming_msg == '3':
        user_state[sender] = 'waiting_for_delete_info'
        response.message("❌ Remember the ID of the expense you'd like to delete? Or the date you entered?\n"
                        "👉 Type the ID (e.g., '5') or the date (e.g., '2025-03-19').")

    elif user_state.get(sender) == 'waiting_for_delete_info':
        id_pattern = r'^\d+$'  # Pattern to match ID
        date_pattern = r'^\d{4}-\d{2}-\d{2}$'  # Pattern to match date (YYYY-MM-DD)

        data = sheet.get_all_values()

        if re.match(id_pattern, incoming_msg):  # Delete by ID
            delete_id = int(incoming_msg)
            row_index = next((i for i, row in enumerate(data, start=1) if row[0] == str(delete_id)), None)
            if row_index:
                sheet.delete_rows(row_index)
                print("deleted id ")
                response.message(f"✅ Expense with ID {delete_id} deleted successfully.")
            else:
                response.message(f"❌ No expense found with ID {delete_id}.")
            user_state[sender] = None  # Clear state after deleting

        elif re.match(date_pattern, incoming_msg):  # Search by Date
            delete_date = incoming_msg
            matching_rows = [row for row in data if row[1].startswith(delete_date)]

            if matching_rows:
                # ✅ Store the matched expenses temporarily to handle next step
                temp_delete_data[sender] = matching_rows

                message = f"📅 *Expenses on {delete_date}:*\n"
                for row in matching_rows:
                    message += f"➡️ ID: {row[0]}, ₹{row[2]} on {row[3]}\n"
                
                message += "\n👉 Please type the ID of the expense you'd like to delete."
                user_state[sender] = 'waiting_for_delete_id'  # Move to next state
                response.message(message)
            else:
                response.message(f"❌ No expenses found on {delete_date}.")
                user_state[sender] = None

        else:
            response.message("❌ Invalid input! Please enter a valid ID or date (YYYY-MM-DD).")

    # DELETE AFTER SHOWING EXPENSES
    elif user_state.get(sender) == 'waiting_for_delete_id':
        delete_id = incoming_msg.strip()
        matching_rows = temp_delete_data.get(sender, [])

        if any(row[0] == delete_id for row in matching_rows):
            row_index = next((i for i, row in enumerate(data, start=1) if row[0] == delete_id), None)
            if row_index:
                deleted_entry = data[row_index - 1]
                sheet.delete_row(row_index)
                response.message(f"✅ Deleted expense:\n➡️ ₹{deleted_entry[2]} on {deleted_entry[3]}")
            else:
                response.message(f"❌ No expense found with ID {delete_id}.")
        else:
            response.message(f"❌ Invalid ID! Please provide a valid ID from the list.")

        # Clean up state and temp data
        user_state[sender] = None
        temp_delete_data[sender] = None

    elif incoming_msg == '5':
        print("entered help")
        response.message("❓ Help - Contact irfanaibrahim03phi@gmail.com")

    elif incoming_msg == '4':
        print("entered 4")
        user_state[sender] = 'waiting_for_date'
        response.message("📅 Please enter a specific date (YYYY-MM-DD) or a date range (YYYY-MM-DD to YYYY-MM-DD):")

    # If user has sent a date or range
    elif sender in user_state and user_state[sender] == 'waiting_for_date':
        date_pattern = r'^\d{4}-\d{2}-\d{2}$'
        range_pattern = r'^(\d{4}-\d{2}-\d{2})\s*to\s*(\d{4}-\d{2}-\d{2})$'

        # Handle single date request
        if re.match(date_pattern, incoming_msg):
            date = incoming_msg.strip()
            print("date", date)
            print("sender", sender)
            expenses = [
                row for row in sheet.get_all_values()
                if row[4] == sender  # Match sender
                and re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', row[1])  # Check if it's a valid datetime (skip budget row)
                and datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d') == date  # Match date
            ]

            print("date from sheet", expenses)
            if expenses:
                print("there are expenses")
                summary = f"📅 *Expenses on {date}:*\n"
                total_expense = 0
                for row in expenses:
                    timestamp = row[1]  # Keep the full datetime if needed
                    print("timestamp", timestamp)
                    amount = float(row[2])
                    print("amount", amount)
                    category = row[3]
                    print("category", category)
                    summary += f"➡️ {timestamp}: ₹{amount} on {category}\n"
                    total_expense += amount
                summary += f"\n💰 *Total Spent:* ₹{total_expense}"
            else:
                summary = f"❌ No expenses logged on {date}."

            user_state[sender] = None 
            print("summary", summary)
            response.message(summary)

    # Handle date range request
    elif re.match(range_pattern, incoming_msg) and sender in user_state and user_state[sender] == 'waiting_for_date':
        start_date, end_date = re.match(range_pattern, incoming_msg).groups()
        expenses = [
            row for row in sheet.get_all_values()
            if row[3] == sender and start_date <= datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d') <= end_date
        ]
        if expenses:
            summary = f"📅 *Expenses from {start_date} to {end_date}:*\n"
            total_expense = 0
            for row in expenses:
                date = row[0]  # Full datetime
                amount = float(row[1])
                category = row[2]
                summary += f"➡️ {date}: ₹{amount} on {category}\n"
                total_expense += amount
            summary += f"\n💰 *Total Spent:* ₹{total_expense}"
        else:
            summary = f"❌ No expenses logged between {start_date} and {end_date}."

        user_state[sender] = None  # Clear state
        response.message(summary)

    

    else:
        response.message("❌ Invalid option! Please try again.")

    return str(response)


# === Start Flask App ===
if __name__ == "__main__":
    app.run(port=5000, debug=True)
