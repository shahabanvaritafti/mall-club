import sqlite3
import os
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="Billing & Charge Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "billing.db")
TEMPLATE_PATH = os.path.join(BASE_DIR, "bill.html")

ZARINPAL_REQUEST_URL = "https://sandbox.zarinpal.com/pg/rest/WebGate/PaymentRequest.json"
ZARINPAL_STARTPAY_URL = "https://sandbox.zarinpal.com/pg/StartPay/"
ZARINPAL_VERIFY_URL = "https://sandbox.zarinpal.com/pg/rest/WebGate/PaymentVerification.json"
MERCHANT_ID = "00000000-0000-0000-0000-000000000000"
SERVER_IP = "http://188.121.107.170:8001"

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_billing_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS charge_invoices (
            invoice_id TEXT PRIMARY KEY,
            unit_id TEXT NOT NULL,
            shop_name TEXT NOT NULL,
            tenant_name TEXT,
            mobile TEXT NOT NULL,
            period TEXT NOT NULL,
            base_charge INTEGER NOT NULL,
            utility_charge INTEGER DEFAULT 0,
            arrears INTEGER DEFAULT 0,
            total_amount INTEGER NOT NULL,
            status TEXT DEFAULT 'PENDING',
            due_date TEXT,
            authority TEXT,
            rrn TEXT,
            payment_method TEXT,
            paid_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        INSERT OR IGNORE INTO charge_invoices 
        (invoice_id, unit_id, shop_name, tenant_name, mobile, period, base_charge, utility_charge, arrears, total_amount, due_date)
        VALUES 
        ('INV-101', 'A-14', 'رزتن', 'آقای شریفی', '09120000000', 'مهر ۱۴۰۵', 3500000, 750000, 0, 4250000, '۱۴۰۵/۰۷/۱۰'),
        ('INV-102', 'B-22', 'کاتوزیان', 'خانم احمدی', '09130000000', 'مهر ۱۴۰۵', 5000000, 1200000, 500000, 6700000, '۱۴۰۵/۰۷/۰۸')
    """)
    conn.commit()
    conn.close()

init_billing_db()

class ManualSettleRequest(BaseModel):
    invoice_id: str
    rrn: str
    payment_method: str = "POS"

@app.get("/view/{invoice_id}", response_class=HTMLResponse)
def view_invoice(invoice_id: str):
    if not os.path.exists(TEMPLATE_PATH):
        raise HTTPException(status_code=500, detail="فایل bill.html یافت نشد.")
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/api/invoice/{invoice_id}")
def get_invoice_data(invoice_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM charge_invoices WHERE invoice_id = ?", (invoice_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="صورت‌حساب یافت نشد")
    return dict(row)

@app.get("/pay/{invoice_id}")
def pay_invoice(invoice_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM charge_invoices WHERE invoice_id = ?", (invoice_id,))
    inv = cursor.fetchone()

    if not inv:
        conn.close()
        raise HTTPException(status_code=404, detail="صورت‌حساب یافت نشد")
    if inv["status"] == "PAID":
        conn.close()
        return RedirectResponse(url=f"/view/{invoice_id}")

    payload = {
        "MerchantID": MERCHANT_ID,
        "Amount": inv["total_amount"],
        "Description": f"شارژ واحد {inv['unit_id']} - فاکتور {invoice_id}",
        "CallbackURL": f"{SERVER_IP}/callback?invoice_id={invoice_id}",
        "Mobile": inv["mobile"]
    }

    try:
        res = requests.post(ZARINPAL_REQUEST_URL, json=payload, timeout=10).json()
        if res.get("Status") == 100:
            authority = res.get("Authority")
            cursor.execute("UPDATE charge_invoices SET authority = ? WHERE invoice_id = ?", (authority, invoice_id))
            conn.commit()
            conn.close()
            return RedirectResponse(url=f"{ZARINPAL_STARTPAY_URL}{authority}")
        else:
            conn.close()
            raise HTTPException(status_code=500, detail=f"کد خطای درگاه: {res.get('Status')}")
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/callback")
def payment_callback(invoice_id: str, Authority: str, Status: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM charge_invoices WHERE invoice_id = ?", (invoice_id,))
    inv = cursor.fetchone()

    if not inv:
        conn.close()
        raise HTTPException(status_code=404, detail="فاکتور نامعتبر")

    if Status == "OK":
        verify_payload = {
            "MerchantID": MERCHANT_ID,
            "Amount": inv["total_amount"],
            "Authority": Authority
        }
        v_res = requests.post(ZARINPAL_VERIFY_URL, json=verify_payload, timeout=10).json()
        if v_res.get("Status") in [100, 101]:
            ref_id = str(v_res.get("RefID"))
            cursor.execute("""
                UPDATE charge_invoices 
                SET status = 'PAID', rrn = ?, payment_method = 'ONLINE_IPG', paid_at = CURRENT_TIMESTAMP
                WHERE invoice_id = ?
            """, (ref_id, invoice_id))
            conn.commit()
            conn.close()
            return RedirectResponse(url=f"/view/{invoice_id}?payment=success&rrn={ref_id}")

    conn.close()
    return RedirectResponse(url=f"/view/{invoice_id}?payment=failed")

@app.post("/manual-settle")
def manual_settle(data: ManualSettleRequest):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE charge_invoices 
        SET status = 'PAID', rrn = ?, payment_method = ?, paid_at = CURRENT_TIMESTAMP
        WHERE invoice_id = ?
    """, (data.rrn, data.payment_method, data.invoice_id))
    conn.commit()
    conn.close()
    return {"status": "SUCCESS"}

@app.get("/report")
def billing_report():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM charge_invoices ORDER BY created_at DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

if __name__ == "__main__":
    uvicorn.run("billing.app:app", host="0.0.0.0", port=8001, reload=True)
