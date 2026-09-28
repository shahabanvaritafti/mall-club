import sqlite3
import random
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Any
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

# --- ساختارهای داده طبق داکیومنت سامان‌کیش ---
class SepInqueryData(BaseModel):
    cardNumber: Optional[str] = None
    terminalId: Any
    merchantId: Optional[Any] = None
    terminalLang: Optional[int] = 0
    currencyCode: Optional[int] = 0
    posstep: Optional[int] = 0
    requestedTransactionAmount: int
    addData: Optional[str] = ""
    trackingNo: Optional[Any] = None

class SepInqueryEnvelope(BaseModel):
    securityBlock: Optional[str] = None
    inqueryrequest: SepInqueryData

class SepNotifyData(BaseModel):
    trStatus: Optional[int] = 0
    totalAmount: str
    sharedAmountIban: Optional[Any] = None
    rrn: str
    transactionDate: Optional[str] = None
    responseId: Optional[str] = None
    terminalId: str
    trackingNo: Optional[str] = None
    transactionState: Optional[str] = None
    transactionStateDescription: Optional[str] = None

class SepNotifyEnvelope(BaseModel):
    securityBlock: Optional[str] = None
    notifyrequest: SepNotifyData

# --- وب‌سرویس ۱ سامان‌کیش: استعلام تخفیف ---
@app.post("/RequestInquery")
def sep_request_inquery(payload: SepInqueryEnvelope):
    req = payload.inqueryrequest
    terminal_id = str(req.terminalId).strip()
    raw_amount = int(req.requestedTransactionAmount)
    
    # استخراج شماره موبایل از فیلد addData (مثلاً اگر "0912..." یا "mobile:0912..." بود)
    raw_add = str(req.addData or "").strip()
    mobile = raw_add.split(":")[-1].strip() if ":" in raw_add else raw_add
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT store_name FROM stores WHERE terminal_id = ?", (terminal_id,))
    store = cursor.fetchone()
    store_name = store["store_name"] if store else "مهستان"
    
    # بررسی کوپن فعال
    cursor.execute(
        "SELECT id, discount_percent FROM coupons WHERE mobile = ? AND terminal_id = ? AND status = 'ACTIVE' ORDER BY id DESC LIMIT 1",
        (mobile, terminal_id)
    )
    coupon = cursor.fetchone()
    
    discount_amount = 0
    discount_percent = 0
    if coupon:
        discount_percent = coupon["discount_percent"]
        discount_amount = int(raw_amount * (discount_percent / 100))
        
    payable_amount = max(0, raw_amount - discount_amount)
    response_id = f"MHS-{random.randint(100000, 999999)}"
    
    conn.close()
    
    return {
        "ResponseCode": 0,
        "ResponseErrorDescription": "",
        "ResponseId": response_id,
        "TotalPayableAmount": str(payable_amount),
        "SharedAmountIban": [],
        "Preview": [
            f"باشگاه مهستان",
            f"فروشگاه: {store_name[:10]}",
            f"تخفیف: {discount_percent}٪"
        ],
        "UserNotifiable": {
            "FooterMessage": "مرکز خرید مهستان - با تشکر از خرید شما",
            "PrintItem": [
                {
                    "Item": "باشگاه مهستان",
                    "Value": f"تخفیف {discount_percent}٪",
                    "Alignment": 0,
                    "ReceiptType": 2
                }
            ]
        }
    }

# --- وب‌سرویس ۲ سامان‌کیش: تایید نهایی و اعلام تراکنش شاپرک ---
@app.post("/notifyRequest")
def sep_notify_request(payload: SepNotifyEnvelope):
    req = payload.notifyrequest
    terminal_id = str(req.terminalId).strip()
    paid_amount = int(req.totalAmount)
    rrn = str(req.rrn)
    
    conn = get_db()
    cursor = conn.cursor()
    
    # شارژ ۵٪ کش‌بک
    cashback = int(paid_amount * 0.05)
    is_winner = (random.randint(1, 100) == 77)
    
    # پیدا کردن آخرین شماره موبایل فعال در این پایانه
    cursor.execute(
        "SELECT mobile FROM coupons WHERE terminal_id = ? AND status = 'ACTIVE' ORDER BY id DESC LIMIT 1",
        (terminal_id,)
    )
    found = cursor.fetchone()
    mobile = found["mobile"] if found else "نامشخص"
    
    try:
        cursor.execute(
            "INSERT INTO transactions (rrn, mobile, terminal_id, paid_amount, cashback_amount, is_winner) VALUES (?, ?, ?, ?, ?, ?)",
            (rrn, mobile, terminal_id, paid_amount, cashback, is_winner)
        )
        if mobile != "نامشخص":
            cursor.execute(
                "UPDATE coupons SET status = 'USED' WHERE id = (SELECT id FROM coupons WHERE mobile = ? AND terminal_id = ? AND status = 'ACTIVE' ORDER BY id DESC LIMIT 1)",
                (mobile, terminal_id)
            )
            cursor.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE mobile = ?", (cashback, mobile))
        conn.commit()
    except Exception as e:
        pass
    finally:
        conn.close()
        
    return {
        "Status": True,
        "ErrorCode": "0",
        "ErrorDesciption": "",
        "RejectTransactionStatus": False
    }

# --- اندپوینت‌های وب و داشبورد مهستان ---
@app.get("/")
def home():
    return FileResponse("static/index.html")

@app.get("/admin")
def serve_admin():
    return FileResponse("static/admin.html")

@app.get("/pos")
def serve_pos():
    return FileResponse("static/pos.html")

class SpinRequest(BaseModel):
    mobile: str
    discount_percent: int
    terminal_id: str

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
