import os
import json
import sqlite3
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from google import genai

# =========================
# ENV VARIABLES
# =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

# =========================
# DATABASE
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

def clean_json(text):
    text = text.strip()

    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()

    return text

def parse_with_gemini(user_text):
    prompt = f"""
Extract structured data from this:

"{user_text}"

STRICT RULES:
- Return ONLY pure JSON
- NO markdown
- NO explanation
- NO backticks

Format:
{{
  "amount": number,
  "category": string,
  "account": string,
  "type": "expense" or "income"
}}
"""

    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt
    )

    return response.text

# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 AI Expense Tracker Bot\n\n"
        "Examples:\n"
        "👉 Petrol 500 from HDFC\n"
        "👉 Salary 20000 in HDFC\n\n"
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
# MAIN HANDLER
# =========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_text = update.message.text

    try:
        raw = parse_with_gemini(user_text)
        print("RAW GEMINI:", raw)  # debug log

        cleaned = clean_json(raw)
        data = json.loads(cleaned)

    except Exception as e:
        print("ERROR:", e)
        await update.message.reply_text("❌ Couldn't understand. Try: Petrol 500 from HDFC")
        return

    amount = data.get("amount")
    category = normalize(data.get("category", "other"))
    account = normalize(data.get("account", "cash"))
    txn_type = data.get("type")

    if not amount or not account or not txn_type:
        await update.message.reply_text("❌ Missing data. Try again.")
        return

    # check account
    cursor.execute("""
    SELECT balance FROM accounts WHERE user_id=? AND name=?
    """, (user_id, account))

    row = cursor.fetchone()

    if not row:
        await update.message.reply_text(f"⚠️ Account '{account}' not found. Use /add_account")
        return

    # update balance
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

    # insert transaction
    cursor.execute("""
    INSERT INTO transactions (user_id, amount, category, account, type)
    VALUES (?, ?, ?, ?, ?)
    """, (user_id, amount, category, account, txn_type))

    conn.commit()

    await update.message.reply_text(
        f"✅ {category.title()} ₹{amount} {'from' if txn_type=='expense' else 'to'} {account.upper()} recorded."
    )

# =========================
# APP START
# =========================
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("add_account", add_account))
app.add_handler(CommandHandler("balance", balance))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("🚀 Bot is running...")
app.run_polling()
