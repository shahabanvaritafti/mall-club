import sqlite3
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Mahestan Customer Club Core API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "mahestan.db"

# ----------------- Database Initialization -----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # جدول پایانه‌های فروشگاهی پاساژ مهستان
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stores (
        terminal_id TEXT PRIMARY KEY,
        store_name TEXT NOT NULL
    )
    """)
    
    # جدول کاربران و موجودی کیف‌پول (کش‌بک)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        mobile TEXT PRIMARY KEY,
        wallet_balance INTEGER DEFAULT 0
    )
    """)
    
    # جدول کوپن‌های تخصیص‌یافته از گردونه شانس
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS coupons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mobile TEXT NOT NULL,
        terminal_id TEXT NOT NULL,
        discount_percent INTEGER NOT NULL,
        status TEXT DEFAULT 'ACTIVE',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # جدول لاگ تراکنش‌های تسویه‌شده پای پوز
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        rrn TEXT PRIMARY KEY,
        mobile TEXT NOT NULL,
        terminal_id TEXT NOT NULL,
        paid_amount INTEGER NOT NULL,
        cashback_amount INTEGER NOT NULL,
        is_winner BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # ثبت پایانه تستی پیش‌فرض (فروشگاه زاگرس)
    cursor.execute("INSERT OR IGNORE INTO stores (terminal_id, store_name) VALUES ('11112222', 'پوشاک زاگرس')")
    
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ----------------- Pydantic Models -----------------
class SpinRequest(BaseModel):
    mobile: str
    discount_percent: int
    terminal_id: str = "11112222"

class InquiryRequest(BaseModel):
    mobile: str
    terminal_id: str
    amount: int

class SettleRequest(BaseModel):
    mobile: str
    terminal_id: str
    paid_amount: int
    rrn: str

# ----------------- 1. Spin to Win Endpoint -----------------
@app.post("/api/spin")
def spin_wheel(payload: SpinRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    # اطمینان از وجود کاربر
    cursor.execute("INSERT OR IGNORE INTO users (mobile) VALUES (?)", (payload.mobile,))
    
    # ثبت کوپن فعال
    cursor.execute(
        "INSERT INTO coupons (mobile, terminal_id, discount_percent, status) VALUES (?, ?, ?, 'ACTIVE')",
        (payload.mobile, payload.terminal_id, payload.discount_percent)
    )
    conn.commit()
    conn.close()
    
    return {
        "status": "OK",
        "message": f"کوپن {payload.discount_percent}٪ برای شما فعال شد."
    }

# ----------------- 2. POS Inquiry Endpoint -----------------
@app.post("/api/pos/inquiry")
def pos_inquiry(payload: InquiryRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    # ۱. اعتبارسنجی پایانه
    cursor.execute("SELECT store_name FROM stores WHERE terminal_id = ?", (payload.terminal_id,))
    store = cursor.fetchone()
    if not store:
        conn.close()
        raise HTTPException(status_code=404, detail="پایانه فروشگاهی در سامانه مهستان یافت نشد.")
    
    store_name = store["store_name"]
    
    # ۲. بررسی کوپن فعال گردونه برای این شماره و این مغازه
    cursor.execute(
        "SELECT id, discount_percent FROM coupons WHERE mobile = ? AND terminal_id = ? AND status = 'ACTIVE' ORDER BY id DESC LIMIT 1",
        (payload.mobile, payload.terminal_id)
    )
    coupon = cursor.fetchone()
    
    discount_amount = 0
    if coupon:
        discount_percent = coupon["discount_percent"]
        discount_amount = int(payload.amount * (discount_percent / 100))
        
    payable_amount = payload.amount - discount_amount
    conn.close()
    
    return {
        "status": "OK",
        "store_name": store_name,
        "original_amount": payload.amount,
        "discount_amount": discount_amount,
        "payable_amount": payable_amount,
        "receipt_header": "باشگاه مشتریان مرکز خرید مهستان"
    }

# ----------------- 3. POS Settle Endpoint -----------------
@app.post("/api/pos/settle")
def pos_settle(payload: SettleRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    # بررسی تکراری نبودن شماره تراکنش شاپرک (RRN)
    cursor.execute("SELECT rrn FROM transactions WHERE rrn = ?", (payload.rrn,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="این تراکنش قبلاً تسویه شده است.")
    
    # ۱. ابطال کوپن مصرف‌شده
    cursor.execute(
        "UPDATE coupons SET status = 'USED' WHERE mobile = ? AND terminal_id = ? AND status = 'ACTIVE'",
        (payload.mobile, payload.terminal_id)
    )
    
    # ۲. محاسبه ۵٪ کش‌بک
    cashback = int(payload.paid_amount * 0.05)
    
    # ثبت کاربر در صورت عدم وجود و شارژ کیف پول
    cursor.execute("INSERT OR IGNORE INTO users (mobile, wallet_balance) VALUES (?, 0)", (payload.mobile,))
    cursor.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE mobile = ?", (cashback, payload.mobile))
    
    # دریافت موجودی لحظه‌ای
    cursor.execute("SELECT wallet_balance FROM users WHERE mobile = ?", (payload.mobile,))
    current_wallet = cursor.fetchone()["wallet_balance"]
    
    # ۳. ارزیابی قرعه‌کشی آنی (ساعت ۱۸ الی ۲۲ روزهای یکشنبه(۶)، دوشنبه(۰) و سه‌شنبه(۱))
    now = datetime.now()
    weekday = now.weekday()
    hour = now.hour
    
    is_winner = False
    prize_amount = 0
    
    # بررسی شرط زمان و سقف ۳ برنده در روز
    if weekday in [6, 0, 1] and 18 <= hour < 22:
        cursor.execute("SELECT COUNT(*) as win_count FROM transactions WHERE is_winner = 1 AND DATE(created_at) = DATE('now')")
        daily_wins = cursor.fetchone()["win_count"]
        if daily_wins < 3:
            is_winner = True
            prize_amount = 10000000  # جایزه ۱ میلیون تومانی به ریال
            cursor.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE mobile = ?", (prize_amount, payload.mobile))
            current_wallet += prize_amount

    # ثبت لاگ تراکنش
    cursor.execute(
        "INSERT INTO transactions (rrn, mobile, terminal_id, paid_amount, cashback_amount, is_winner) VALUES (?, ?, ?, ?, ?, ?)",
        (payload.rrn, payload.mobile, payload.terminal_id, payload.paid_amount, cashback, 1 if is_winner else 0)
    )
    
    conn.commit()
    conn.close()
    
    # متن پیام چاپ رسید کارتخوان
    pos_msg = f"اعتبار افزوده: {cashback:,} ریال"
    if is_winner:
        pos_msg = f"تبریک! برنده جایزه ۱ میلیونی شدید | {pos_msg}"
        
    return {
        "status": "SUCCESS",
        "cashback_added": cashback,
        "instant_prize_won": prize_amount,
        "is_instant_winner": is_winner,
        "pos_message": pos_msg,
        "total_wallet": current_wallet
    }
