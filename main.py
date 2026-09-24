import os
import random
from datetime import datetime
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Mahestan Loyalty Hub")

# ۱. تعریف فروشگاه‌ها با شناسه یکتا (Store ID)
STORES = {
    "shop_1": {"name": "پوشاک زاگرس", "terminal_id": "11112222"},
    "shop_2": {"name": "کافه ویونا", "terminal_id": "33334444"},
    "shop_3": {"name": "طلای آفتاب", "terminal_id": "55556666"},
    "shop_4": {"name": "ادکلن باران", "terminal_id": "77778888"},
}

# نگاشت سریع: شماره ترمینال -> شناسه فروشگاه
TERMINAL_TO_STORE = {info["terminal_id"]: s_id for s_id, info in STORES.items()}

# ۲. جوایز گردونه مستقیماً به store_id متصل هستند
PRIZES_CONFIG = [
    {"index": 0, "title": "۱۰٪ پوشاک زاگرس", "store_id": "shop_1", "discount_pct": 0.10},
    {"index": 1, "title": "۱۵٪ کافه ویونا", "store_id": "shop_2", "discount_pct": 0.15},
    {"index": 2, "title": "۵٪ طلای آفتاب", "store_id": "shop_3", "discount_pct": 0.05},
    {"index": 3, "title": "۲۰٪ ادکلن باران", "store_id": "shop_4", "discount_pct": 0.20},
    {"index": 4, "title": "۲۰٪ کافه ویونا", "store_id": "shop_2", "discount_pct": 0.20},
    {"index": 5, "title": "۱۵٪ پوشاک زاگرس", "store_id": "shop_1", "discount_pct": 0.15}
]

# قوانین قرعه‌کشی آنی
ALLOWED_WEEKDAYS = [6, 0, 1]  # یکشنبه (6)، دوشنبه (0)، سه‌شنبه (1)
CAMPAIGN_START_HOUR = 18
CAMPAIGN_END_HOUR = 22
DAILY_WINNERS_LIMIT = 3
INSTANT_PRIZE_AMOUNT = 1_000_000

active_coupons = {}
wallets = {}
daily_winners_count = {}

class SpinRequest(BaseModel):
    mobile: str

class InquiryRequest(BaseModel):
    mobile: str
    terminal_id: str
    amount: int

class SettleRequest(BaseModel):
    mobile: str
    terminal_id: str
    paid_amount: int
    rrn: str

def check_instant_win_eligibility():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    if now.weekday() not in ALLOWED_WEEKDAYS:
        return False, "خارج از روزهای کمپین"
    if not (CAMPAIGN_START_HOUR <= now.hour < CAMPAIGN_END_HOUR):
        return False, "خارج از بازه زمانی کمپین"
    if daily_winners_count.get(today_str, 0) >= DAILY_WINNERS_LIMIT:
        return False, "تکمیل ظرفیت جوایز امروز"

    return True, today_str

@app.post("/api/spin")
def spin(req: SpinRequest):
    prize = random.choice(PRIZES_CONFIG)
    # کوپن با شناسه دقیق فروشگاه ثبت می‌شود
    active_coupons[req.mobile] = {
        "store_id": prize["store_id"],
        "discount_pct": prize["discount_pct"],
        "prize_title": prize["title"]
    }
    return {"prize_index": prize["index"], "prize_title": prize["title"]}

@app.post("/api/pos/inquiry")
def pos_inquiry(req: InquiryRequest):
    store_id = TERMINAL_TO_STORE.get(req.terminal_id)
    store_info = STORES.get(store_id, {"name": "مرکز خرید مهستان"})
    
    discount = 0
    coupon = active_coupons.get(req.mobile)

    # شرط شفاف: آیا کوپن مشتری دقیقاً برای همین فروشگاه است؟
    if coupon and coupon["store_id"] == store_id:
        discount = int(req.amount * coupon["discount_pct"])

    payable = max(0, req.amount - discount)
    return {
        "status": "OK",
        "store_name": store_info["name"],
        "original_amount": req.amount,
        "discount_amount": discount,
        "payable_amount": payable,
        "receipt_header": "باشگاه مشتریان مرکز خرید مهستان"
    }

@app.post("/api/pos/settle")
def pos_settle(req: SettleRequest):
    active_coupons.pop(req.mobile, None)
    cashback = int(req.paid_amount * 0.05)

    eligible, info = check_instant_win_eligibility()
    won_cash = 0
    is_winner = False

    if eligible:
        today_key = info
        if random.random() < 0.30:
            is_winner = True
            won_cash = INSTANT_PRIZE_AMOUNT
            daily_winners_count[today_key] = daily_winners_count.get(today_key, 0) + 1

    total_credit = cashback + won_cash
    wallets[req.mobile] = wallets.get(req.mobile, 0) + total_credit

    pos_msg = (
        f"تبریک! برنده جایزه ۱ میلیون تومانی شدید!"
        if is_winner
        else "تراکنش با موفقیت ثبت شد."
    )

    return {
        "status": "SUCCESS",
        "cashback_added": cashback,
        "instant_prize_won": won_cash,
        "is_instant_winner": is_winner,
        "pos_message": pos_msg,
        "total_wallet": wallets[req.mobile]
    }

if os.path.exists("/root/mahestan/static"):
    app.mount("/", StaticFiles(directory="/root/mahestan/static", html=True), name="static")
