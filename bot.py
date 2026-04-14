import os
import json
import sqlite3
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
import google.generativeai as genai

# =========================
# LOAD ENV VARIABLES
# =========================
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# =========================
# DATABASE SETUP
# =========================
conn = sqlite3.connect("expenses.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS accounts (
    user_id INTEGER,
    name TEXT,
    balance REAL,
    PRIMARY KEY (user_id, name)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    category TEXT,
    account TEXT,
    type TEXT
)
""")

conn.commit()

# =========================
# HELPERS
# =========================
def normalize(text):
    return text.strip().lower()

def parse_with_gemini(user_text):
    prompt = f"""
You are a finance assistant.

Extract structured data from user input.

Rules:
- If it's expense → type = "expense"
- If income → type = "income"
- Category should be simple (Food, Petrol, Salary, etc.)
- Account should be like bank name (HDFC, ICICI, Cash)

Message: "{user_text}"

Return ONLY valid JSON in this format:
{{
  "amount": number,
  "category": string,
  "account": string,
  "type": "expense" or "income"
}}
"""
    response = model.generate_content(prompt)
    return response.text

# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to AI Expense Tracker Bot!\n\n"
        "Example:\n"
        "👉 Petrol 500 from HDFC\n"
        "👉 Salary 20000 in ICICI\n\n"
        "Commands:\n"
        "/add_account HDFC 10000\n"
        "/balance"
    )

async def add_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    try:
        name = normalize(context.args[0])
        balance = float(context.args[1])
    except:
        await update.message.reply_text("Usage: /add_account HDFC 10000")
        return

    cursor.execute("""
    INSERT OR REPLACE INTO accounts (user_id, name, balance)
    VALUES (?, ?, ?)
    """, (user_id, name, balance))

    conn.commit()

    await update.message.reply_text(f"✅ Account {name.upper()} added with ₹{balance}")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    cursor.execute("""
    SELECT name, balance FROM accounts WHERE user_id=?
    """, (user_id,))
    
    rows = cursor.fetchall()

    if not rows:
        await update.message.reply_text("No accounts found.")
        return

    msg = "💰 Your Balances:\n\n"
    for name, bal in rows:
        msg += f"{name.upper()} : ₹{bal}\n"

    await update.message.reply_text(msg)

# =========================
# MAIN MESSAGE HANDLER
# =========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_text = update.message.text

    # Step 1: Gemini parsing
    try:
        raw = parse_with_gemini(user_text)
        data = json.loads(raw)
    except:
        await update.message.reply_text("❌ Couldn't understand. Try: Petrol 500 from HDFC")
        return

    amount = data.get("amount")
    category = normalize(data.get("category", "other"))
    account = normalize(data.get("account", "cash"))
    txn_type = data.get("type")

    if not amount or not account or not txn_type:
        await update.message.reply_text("❌ Missing data. Try again.")
        return

    # Step 2: Check account exists
    cursor.execute("""
    SELECT balance FROM accounts WHERE user_id=? AND name=?
    """, (user_id, account))

    row = cursor.fetchone()

    if not row:
        await update.message.reply_text(f"⚠️ Account '{account}' not found. Add using /add_account")
        return

    # Step 3: Update balance
    if txn_type == "expense":
        cursor.execute("""
        UPDATE accounts SET balance = balance - ?
        WHERE user_id=? AND name=?
        """, (amount, user_id, account))
    else:
        cursor.execute("""
        UPDATE accounts SET balance = balance + ?
        WHERE user_id=? AND name=?
        """, (amount, user_id, account))

    # Step 4: Save transaction
    cursor.execute("""
    INSERT INTO transactions (user_id, amount, category, account, type)
    VALUES (?, ?, ?, ?, ?)
    """, (user_id, amount, category, account, txn_type))

    conn.commit()

    # Step 5: Reply
    await update.message.reply_text(
        f"✅ {category.title()} ₹{amount} {'from' if txn_type=='expense' else 'to'} {account.upper()} recorded."
    )

# =========================
# MAIN APP
# =========================
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("add_account", add_account))
app.add_handler(CommandHandler("balance", balance))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("🚀 Bot is running...")
app.run_polling()
