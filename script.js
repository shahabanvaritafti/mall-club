let currentRotation = 0;
let isSpinning = false;

function spinWheel() {
  const mobile = document.getElementById("mobileInput").value.trim();
  const messageEl = document.getElementById("resultMessage");

  if (!mobile || mobile.length < 11 || !mobile.startsWith("09")) {
    alert("لطفاً یک شماره موبایل معتبر ۱۱ رقمی وارد کنید.");
    return;
  }

  if (isSpinning) return;
  isSpinning = true;
  messageEl.innerText = "گردونه در حال چرخش...";

  const randomDegree = Math.floor(Math.random() * 360);
  currentRotation += 1440 + randomDegree;

  const wheel = document.getElementById("wheel");
  wheel.style.transform = `rotate(${currentRotation}deg)`;

  setTimeout(() => {
    isSpinning = false;
    messageEl.innerHTML = `🎉 تبریک! یک کوپن تخفیف ۲۰٪ خرید صنف کافی‌شاپ برای شماره <b>${mobile}</b> فعال شد.<br><small>مهلت استفاده: تا ۴۸ ساعت آینده پای پوزهای سامان‌کیش مرکز خرید</small>`;
  }, 4000);
}
