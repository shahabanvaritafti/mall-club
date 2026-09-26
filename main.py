import sqlite3
import random
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os

app = FastAPI(title="Mahestan Club Core API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

DB_FILE = "mahestan.db"

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stores (
            terminal_id TEXT PRIMARY KEY,
            store_name TEXT NOT NULL,
            default_discount INTEGER DEFAULT 5
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            mobile TEXT PRIMARY KEY,
            wallet_balance INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
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
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rrn TEXT UNIQUE NOT NULL,
            mobile TEXT NOT NULL,
            terminal_id TEXT NOT NULL,
            paid_amount INTEGER NOT NULL,
            cashback_amount INTEGER NOT NULL,
            is_winner BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    initial_stores = [
        ("45034950", "رزتن", 10),
        ("99031044", "ماریوسونیک", 12),
        ("9946922", "لوکا", 8),
        ("99225982", "کاتوزیان", 20),
        ("099034315", "زیرو", 5),
        ("45251385", "طلای اکسین", 2),
        ("99231122", "دیپ لوک", 20),
        ("99445302", "کنزپلاس", 5),
        ("99354094", "چیلک", 5)
    ]
    cursor.executemany("INSERT OR REPLACE INTO stores (terminal_id, store_name, default_discount) VALUES (?, ?, ?)", initial_stores)
    
    conn.commit()
    conn.close()

init_db()

class SpinRequest(BaseModel):
    mobile: str
    discount_percent: int
    terminal_id: str

class InquiryRequest(BaseModel):
    mobile: str
    terminal_id: str
    amount: int

class SettleRequest(BaseModel):
    mobile: str
    terminal_id: str
    paid_amount: int
    rrn: str

@app.get("/")
def home():
    return FileResponse("static/index.html")

@app.get("/admin")
def serve_admin():
    return FileResponse("static/admin.html")

@app.get("/pos")
def serve_pos():
    return FileResponse("static/pos.html")

@app.get("/api/stores")
def get_stores():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT terminal_id, store_name, default_discount FROM stores")
    stores = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return stores

@app.post("/api/spin")
def spin_wheel(data: SpinRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("INSERT OR IGNORE INTO users (mobile) VALUES (?)", (data.mobile,))
    cursor.execute(
        "INSERT INTO coupons (mobile, terminal_id, discount_percent, status) VALUES (?, ?, ?, 'ACTIVE')",
        (data.mobile, data.terminal_id, data.discount_percent)
    )
    conn.commit()
    conn.close()
    return {"status": "OK", "message": f"کوپن {data.discount_percent}٪ با موفقیت ثبت شد."}

@app.post("/api/pos/inquiry")
def pos_inquiry(data: InquiryRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT store_name FROM stores WHERE terminal_id = ?", (data.terminal_id,))
    store = cursor.fetchone()
    store_name = store["store_name"] if store else "فروشگاه مهستان"
    
    cursor.execute(
        "SELECT id, discount_percent FROM coupons WHERE mobile = ? AND terminal_id = ? AND status = 'ACTIVE' ORDER BY id DESC LIMIT 1",
        (data.mobile, data.terminal_id)
    )
    coupon = cursor.fetchone()
    
    discount_amount = 0
    if coupon:
        discount_amount = int(data.amount * (coupon["discount_percent"] / 100))
        
    payable_amount = max(0, data.amount - discount_amount)
    conn.close()
    
    return {
        "status": "OK",
        "store_name": store_name,
        "original_amount": data.amount,
        "discount_amount": discount_amount,
        "payable_amount": payable_amount,
        "receipt_header": "باشگاه مشتریان مرکز خرید مهستان"
    }

@app.post("/api/pos/settle")
def pos_settle(data: SettleRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cashback = int(data.paid_amount * 0.05)
    is_winner = (random.randint(1, 100) == 77)
    instant_prize = 10000000 if is_winner else 0
    
    try:
        cursor.execute(
            "INSERT INTO transactions (rrn, mobile, terminal_id, paid_amount, cashback_amount, is_winner) VALUES (?, ?, ?, ?, ?, ?)",
            (data.rrn, data.mobile, data.terminal_id, data.paid_amount, cashback, is_winner)
        )
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="این شماره تراکنش قبلاً ثبت شده است.")
        
    cursor.execute(
        "UPDATE coupons SET status = 'USED' WHERE id = (SELECT id FROM coupons WHERE mobile = ? AND terminal_id = ? AND status = 'ACTIVE' ORDER BY id DESC LIMIT 1)",
        (data.mobile, data.terminal_id)
    )
    
    cursor.execute("INSERT OR IGNORE INTO users (mobile) VALUES (?)", (data.mobile,))
    cursor.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE mobile = ?", (cashback + instant_prize, data.mobile))
    
    cursor.execute("SELECT wallet_balance FROM users WHERE mobile = ?", (data.mobile,))
    total_wallet = cursor.fetchone()["wallet_balance"]
    
    conn.commit()
    conn.close()
    
    pos_msg = f"اعتبار افزوده: {cashback:,} ریال"
    if is_winner:
        pos_msg += " | تبریک! شما برنده جایزه ۱ میلیونی شدید!"
        
    return {
        "status": "SUCCESS",
        "cashback_added": cashback,
        "is_instant_winner": is_winner,
        "pos_message": pos_msg,
        "total_wallet": total_wallet
    }

@app.get("/api/admin/overview")
def admin_overview():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as count FROM users")
    total_users = cursor.fetchone()["count"]
    
    cursor.execute("SELECT COALESCE(SUM(wallet_balance), 0) as total FROM users")
    total_wallet = cursor.fetchone()["total"]
    
    cursor.execute("SELECT COUNT(*) as count FROM transactions")
    total_tx = cursor.fetchone()["count"]
    
    cursor.execute("SELECT COUNT(*) as count FROM transactions WHERE is_winner = 1")
    total_winners = cursor.fetchone()["count"]
    
    cursor.execute("""
        SELECT t.rrn, t.mobile, s.store_name, t.paid_amount, t.cashback_amount, t.is_winner, t.created_at
        FROM transactions t
        LEFT JOIN stores s ON t.terminal_id = s.terminal_id
        ORDER BY t.created_at DESC LIMIT 20
    """)
    transactions = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("""
        SELECT c.id, c.mobile, s.store_name, c.discount_percent, c.status, c.created_at
        FROM coupons c
        LEFT JOIN stores s ON c.terminal_id = s.terminal_id
        ORDER BY c.id DESC LIMIT 20
    """)
    coupons = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return {
        "stats": {
            "total_users": total_users,
            "total_wallet": total_wallet,
            "total_tx": total_tx,
            "total_winners": total_winners
        },
        "transactions": transactions,
        "coupons": coupons
    }
