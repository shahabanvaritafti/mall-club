// تنظیمات اتصال به دیتابیس
const SUPABASE_URL = "https://tekokrskxcngnelxdzpm.supabase.co";
const SUPABASE_ANON_KEY = "sb_publishable_v1lOPWjQRNgSWk5yX1Wmkg_9vZDmf0r";
const supabaseClient = supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

let currentRotation = 0;
let isSpinning = false;

// لیست جوایز گردونه (مطابق با قاچ‌های SVG)
const PRIZES = [
  { name: "کافی‌شاپ ۲۰٪", category: "cafe", discount: 20 },
  { name: "پوشاک ۱۵٪", category: "clothing", discount: 15 },
  { name: "۵۰ تومن نقد", category: "cash", discount: 50000 },
  { name: "عطر و آرایشی ۱۰٪", category: "cosmetics", discount: 10 },
  { name: "شانس دوباره", category: "none", discount: 0 },
  { name: "کیف و کفش ۲۵٪", category: "shoes", discount: 25 }
];

async function spinWheel() {
  const mobileInput = document.getElementById("mobileInput");
  const mobile = mobileInput.value.trim();
  const messageEl = document.getElementById("resultMessage");

  if (!mobile || mobile.length < 11 || !mobile.startsWith("09")) {
    alert("لطفاً یک شماره موبایل معتبر ۱۱ رقمی وارد کنید.");
    return;
  }

  if (isSpinning) return;
  isSpinning = true;
  messageEl.innerText = "گردونه در حال چرخش...";

  // انتخاب تصادفی یکی از ۶ جایزه
  const prizeIndex = Math.floor(Math.random() * PRIZES.length);
  const selectedPrize = PRIZES[prizeIndex];

  // محاسبه زاویه چرخش دقیق برای ایستادن روی جایزه
  const segmentAngle = 360 / PRIZES.length;
  const targetRotation = (360 - (prizeIndex * segmentAngle)) - (segmentAngle / 2);
  currentRotation += 1440 + targetRotation;

  const wheel = document.getElementById("wheelContainer");
  wheel.style.transform = `rotate(${currentRotation}deg)`;

  // پس از اتمام چرخش انیمیشن (۴ ثانیه)
  setTimeout(async () => {
    isSpinning = false;

    // ۱. ثبت کوپن در دیتابیس Supabase
    if (selectedPrize.discount > 0) {
      const expiresAt = new Date();
      expiresAt.setHours(expiresAt.getHours() + 48); // ۴۸ ساعت مهلت

      const { error } = await supabaseClient.from("coupons").insert([
        {
          mobile: mobile,
          shop_category: selectedPrize.category,
          discount_percent: selectedPrize.discount <= 100 ? selectedPrize.discount : 0,
          max_discount_amount: selectedPrize.discount > 100 ? selectedPrize.discount : 0,
          expires_at: expiresAt.toISOString()
        }
      ]);

      if (error) {
        console.error("خطا در ثبت کوپن:", error);
      }
    }

    // ۲. نمایش پیام نتیجه به کاربر
    messageEl.innerHTML = `🎉 تبریک! جایزه شما: <b>${selectedPrize.name}</b> برای شماره <b>${mobile}</b> فعال و در سیستم ثبت شد.<br><small>مهلت استفاده: تا ۴۸ ساعت آینده پای پوزهای سامان‌کیش مرکز خرید</small>`;
  }, 4000);
}
