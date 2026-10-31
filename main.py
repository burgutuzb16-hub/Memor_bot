import os
import time
import re
import logging
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ADMIN_IDS = os.getenv("TELEGRAM_ADMIN_USER_IDS", "")
PORT = int(os.getenv("PORT", 10000))

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# Asosiy Menyu
MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "📦 Xomashyo & Qoplar"}, {"text": "🏭 Ostatka (Ishlab chiqarish)"}],
        [{"text": "💰 Kassa Balansi"}, {"text": "📒 Sotuv Daftari"}],
        [{"text": "👥 Qarzdor Mijozlar"}, {"text": "👨‍🔧 Ishchilar Oyligi"}],
        [{"text": "🎁 Bonuslar Tahlili"}],
    ],
    "resize_keyboard": True,
}

# Kassa uchun sana va amallar menyusi
KASSA_DATE_KEYBOARD = {
    "keyboard": [
        [{"text": "💵 Umumiy Balans"}, {"text": "💰 Bugungi Kassa"}],
        [{"text": "💰 Kechagi Kassa"}, {"text": "🧾 Oxirgi 10 ta Kassa amali"}],
        [{"text": "🔙 Asosiy Menyu"}],
    ],
    "resize_keyboard": True,
}

# Sotuv daftari menyusi
SALES_DATE_KEYBOARD = {
    "keyboard": [
        [{"text": "🗓 Bugungi sotuvlar"}, {"text": "🗓 Kechagi sotuvlar"}],
        [{"text": "🗓 Oxirgi 10 ta savdo"}, {"text": "🔙 Asosiy Menyu"}],
    ],
    "resize_keyboard": True,
}

# Render porti uchun mini server
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Memor ERP Bot is running!")

    def log_message(self, format, *args):
        pass

def start_dummy_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
    server.serve_forever()

def is_admin(user_id: int) -> bool:
    admin_list = [i.strip() for i in ADMIN_IDS.split(",") if i.strip()]
    return str(user_id) in admin_list

def send_message(chat_id: int, text: str, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Xabar yuborishda xatolik: {e}")

def get_debts_dict():
    url = f"{SUPABASE_URL}/rest/v1/customer_sales?select=debt,customers(name,phone)"
    res = requests.get(url, headers=HEADERS, timeout=10)
    rows = res.json() if isinstance(res.json(), list) else []

    customers_data = {}
    for r in rows:
        c = r.get("customers")
        if not c:
            continue
        c_name = (c.get("name") or "Noma'lum").strip()
        c_phone = (c.get("phone") or "").strip()
        debt_val = float(r.get("debt") or 0)

        if c_name not in customers_data:
            customers_data[c_name] = {"phone": c_phone, "total_debt": 0.0}
        customers_data[c_name]["total_debt"] += debt_val

    return {k: v for k, v in customers_data.items() if v["total_debt"] > 0}

# ----------------- KASSA FUNKSIYALARI -----------------
def fetch_kassa_by_date(date_str: str):
    url = f"{SUPABASE_URL}/rest/v1/kassa?date=eq.{date_str}&select=type,amount,comment,category,date&order=id.desc"
    res = requests.get(url, headers=HEADERS, timeout=10)
    return res.json() if isinstance(res.json(), list) else []

def format_kassa_response(rows: list, title: str) -> str:
    kirim = sum(float(r.get("amount") or 0) for r in rows if r.get("type") == "kirim")
    chiqim = sum(float(r.get("amount") or 0) for r in rows if r.get("type") == "chiqim")
    sof_foyda = kirim - chiqim

    msg = f"{title}\n\n"
    msg += f"🟢 Jami Kirim: <b>+{kirim:,.0f} so'm</b>\n"
    msg += f"🔴 Jami Chiqim: <b>-{chiqim:,.0f} so'm</b>\n"
    msg += f"💵 Kunlik Sof Qoldiq: <b>{sof_foyda:,.0f} so'm</b>\n"
    msg += "═" * 22 + "\n\n"

    if not rows:
        msg += "<i>Ushbu sanada kassa harakatlari amalga oshirilmagan.</i>"
        return msg

    msg += "<b>Batafsil amallar:</b>\n"
    for i, r in enumerate(rows, 1):
        t = "🟢 Kirim" if r.get("type") == "kirim" else "🔴 Chiqim"
        amt = float(r.get("amount") or 0)
        comment = r.get("comment") or r.get("category") or "Izohsiz"
        msg += f"{i}. {t}: <b>{amt:,.0f} so'm</b>\n   └ <i>{comment}</i>\n"

    return msg

# ----------------- SOTUV FUNKSIYALARI -----------------
def fetch_sales_by_date(date_str: str):
    url = (
        f"{SUPABASE_URL}/rest/v1/customer_sales?"
        f"select=product_name,quantity,price,total,paid,debt,date,customers(name)"
        f"&date=eq.{date_str}&is_ostatka=eq.false&order=id.desc"
    )
    res = requests.get(url, headers=HEADERS, timeout=10)
    return res.json() if isinstance(res.json(), list) else []

def format_sales_response(sales: list, title: str) -> str:
    if not sales:
        return f"{title}\n\n❌ Bu sanada hech qanday sotuv amalga oshirilmagan."

    total_sum = sum(float(s.get("total") or 0) for s in sales)
    total_qty = sum(float(s.get("quantity") or 0) for s in sales)
    total_paid = sum(float(s.get("paid") or 0) for s in sales)

    msg = f"{title}\n"
    msg += f"📦 Jami hajm: <b>{total_qty:,.0f} dona</b>\n"
    msg += f"💵 Jami summa: <b>{total_sum:,.0f} so'm</b>\n"
    msg += f"🟢 To'langan: <b>{total_paid:,.0f} so'm</b>\n"
    msg += "═" * 22 + "\n\n"

    for i, s in enumerate(sales, 1):
        c_name = s.get("customers", {}).get("name") if s.get("customers") else "Mijoz"
        p_name = s.get("product_name") or "Mahsulot"
        qty = float(s.get("quantity") or 0)
        tot = float(s.get("total") or 0)
        paid = float(s.get("paid") or 0)
        debt = float(s.get("debt") or 0)

        msg += (
            f"<b>{i}. {c_name}</b>\n"
            f"   📦 {p_name}: {qty:,.0f} dona ({tot:,.0f} so'm)\n"
            f"   💳 To'landi: {paid:,.0f} so'm"
        )
        if debt > 0:
            msg += f" | 🔴 Qarz: {debt:,.0f} so'm"
        msg += "\n\n"

    return msg

# ----------------- XABARLARNI QAYTA ISHLASH -----------------
def handle_text(chat_id: int, user_id: int, text: str, first_name: str):
    if not is_admin(user_id):
        send_message(chat_id, f"Salom! Siz tizimda ro'yxatdan o'tmagansiz (Telegram ID: {user_id}).")
        return

    # Asosiy Menyu
    if text in ["/start", "start", "🔙 Asosiy Menyu"]:
        send_message(
            chat_id,
            f"Assalomu alaykum, <b>{first_name}</b>!\n"
            "Memor ERP boshqaruv tizimi boti faol.\n\n"
            "💡 <i>Istalgan sanadagi kassa va sotuvlarni ko'rish uchun sanani yozib yuboring (Masalan: 2026-10-19).</i>",
            reply_markup=MAIN_KEYBOARD,
        )

    # 1. XOMASHYO VA QOPLAR
    elif text == "📦 Xomashyo & Qoplar":
        try:
            url = f"{SUPABASE_URL}/rest/v1/materials?select=name,stock,unit&order=name.asc"
            res = requests.get(url, headers=HEADERS, timeout=10)
            materials = res.json()
            if not isinstance(materials, list) or not materials:
                send_message(chat_id, "Omborda xomashyo topilmadi.")
                return

            msg = "📦 <b>Xomashyo & Bo'sh Qoplar Qoldig'i:</b>\n\n"
            for m in materials:
                stock_num = float(m.get("stock") or 0)
                icon = "🟡" if "qop" in m.get("name", "").lower() else "🔹"
                msg += f"{icon} <b>{m.get('name')}</b>: {stock_num:,.0f} {m.get('unit', '')}\n"
            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    # 2. OSTATKA
    elif text == "🏭 Ostatka (Ishlab chiqarish)":
        try:
            p_res = requests.get(f"{SUPABASE_URL}/rest/v1/production?select=quantity", headers=HEADERS, timeout=10)
            s_res = requests.get(f"{SUPABASE_URL}/rest/v1/customer_sales?select=quantity&is_ostatka=eq.false", headers=HEADERS, timeout=10)
            p_data = p_res.json() if isinstance(p_res.json(), list) else []
            s_data = s_res.json() if isinstance(s_res.json(), list) else []

            jami_ishlab_chiqarildi = sum(float(x.get("quantity") or 0) for x in p_data)
            jami_sotildi = sum(float(x.get("quantity") or 0) for x in s_data)
            qoldiq_qop = max(0, jami_ishlab_chiqarildi - jami_sotildi)

            msg = (
                "🏭 <b>Ostatka (Zanjirli Balans):</b>\n\n"
                f"🟢 Jami Ishlab Chiqarildi: <b>{jami_ishlab_chiqarildi:,.0f} qop</b>\n"
                f"🔴 Jami Sotildi / Chiqim: <b>{jami_sotildi:,.0f} qop</b>\n"
                f"📦 <b>Ombordagi Haqiqiy Qoldiq: {qoldiq_qop:,.0f} qop</b>"
            )
            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    # 3. KASSA BALANSI BOSILGANDA
    elif text == "💰 Kassa Balansi":
        send_message(
            chat_id,
            "💰 <b>Kassa bo'limi</b>\n\n"
            "Kerakli bandni tanlang yoki ma'lum bir sanani yozib yuboring (Masalan: <code>2026-10-19</code>):",
            reply_markup=KASSA_DATE_KEYBOARD,
        )

    elif text == "💵 Umumiy Balans":
        try:
            url = f"{SUPABASE_URL}/rest/v1/kassa?select=type,amount"
            res = requests.get(url, headers=HEADERS, timeout=10)
            rows = res.json() if isinstance(res.json(), list) else []

            kirim = sum(float(r.get("amount") or 0) for r in rows if r.get("type") == "kirim")
            chiqim = sum(float(r.get("amount") or 0) for r in rows if r.get("type") == "chiqim")
            qoldiq = kirim - chiqim

            msg = (
                "💰 <b>Umumiy Kassa Balansi:</b>\n\n"
                f"🟢 Jami Kirim: <b>{kirim:,.0f} so'm</b>\n"
                f"🔴 Jami Chiqim: <b>{chiqim:,.0f} so'm</b>\n"
                f"💵 <b>Hozirgi Naqd Qoldiq: {qoldiq:,.0f} so'm</b>"
            )
            send_message(chat_id, msg, reply_markup=KASSA_DATE_KEYBOARD)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    elif text == "💰 Bugungi Kassa":
        today_str = datetime.now().strftime("%Y-%m-%d")
        rows = fetch_kassa_by_date(today_str)
        msg = format_kassa_response(rows, f"💰 <b>Bugungi Kassa Hisoboti ({today_str})</b>")
        send_message(chat_id, msg, reply_markup=KASSA_DATE_KEYBOARD)

    elif text == "💰 Kechagi Kassa":
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        rows = fetch_kassa_by_date(yesterday_str)
        msg = format_kassa_response(rows, f"💰 <b>Kechagi Kassa Hisoboti ({yesterday_str})</b>")
        send_message(chat_id, msg, reply_markup=KASSA_DATE_KEYBOARD)

    elif text == "🧾 Oxirgi 10 ta Kassa amali":
        try:
            url = f"{SUPABASE_URL}/rest/v1/kassa?select=type,amount,comment,category,date&order=id.desc&limit=10"
            res = requests.get(url, headers=HEADERS, timeout=10)
            rows = res.json() if isinstance(res.json(), list) else []
            msg = "🧾 <b>Oxirgi 10 ta Kassa Amaliyoti:</b>\n\n"
            for r in rows:
                t = "🟢 Kirim" if r.get("type") == "kirim" else "🔴 Chiqim"
                amt = float(r.get("amount") or 0)
                d = r.get("date") or ""
                comm = r.get("comment") or r.get("category") or "Izohsiz"
                msg += f"• [{d}] {t}: <b>{amt:,.0f} so'm</b>\n   └ <i>{comm}</i>\n"
            send_message(chat_id, msg, reply_markup=KASSA_DATE_KEYBOARD)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    # 4. SOTUV DAFTARI
    elif text == "📒 Sotuv Daftari":
        send_message(
            chat_id,
            "📒 <b>Sotuv Daftari bo'limi</b>\n\n"
            "Kerakli bandni tanlang yoki xohlagan sanangizni yozib yuboring:\n"
            "Misol: <code>2026-10-19</code> yoki <code>19.10.2026</code>",
            reply_markup=SALES_DATE_KEYBOARD,
        )

    elif text == "🗓 Bugungi sotuvlar":
        today_str = datetime.now().strftime("%Y-%m-%d")
        sales = fetch_sales_by_date(today_str)
        msg = format_sales_response(sales, f"🗓 <b>Bugungi sotuvlar ({today_str}):</b>")
        send_message(chat_id, msg, reply_markup=SALES_DATE_KEYBOARD)

    elif text == "🗓 Kechagi sotuvlar":
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        sales = fetch_sales_by_date(yesterday_str)
        msg = format_sales_response(sales, f"🗓 <b>Kechagi sotuvlar ({yesterday_str}):</b>")
        send_message(chat_id, msg, reply_markup=SALES_DATE_KEYBOARD)

    elif text == "🗓 Oxirgi 10 ta savdo":
        try:
            url = f"{SUPABASE_URL}/rest/v1/customer_sales?select=product_name,quantity,total,paid,debt,date,customers(name)&is_ostatka=eq.false&order=id.desc&limit=10"
            res = requests.get(url, headers=HEADERS, timeout=10)
            sales = res.json() if isinstance(res.json(), list) else []
            msg = format_sales_response(sales, "📒 <b>Oxirgi 10 ta savdo amaliyoti:</b>")
            send_message(chat_id, msg, reply_markup=SALES_DATE_KEYBOARD)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    # 5. QARZDOR MIJOZLAR
    elif text == "👥 Qarzdor Mijozlar":
        try:
            active_debts = get_debts_dict()
            if not active_debts:
                send_message(chat_id, "✅ Qarzdor mijozlar mavjud emas!")
                return

            total_sum = sum(v["total_debt"] for v in active_debts.values())
            sorted_names = sorted(active_debts.keys(), key=lambda s: s.lower())

            msg = f"👥 <b>QARZDOR MIJOZLAR RO'YXATI</b>\n"
            msg += f"💵 Jami qarz: <b>{total_sum:,.0f} so'm</b>\n"
            msg += f"👤 Qarzdorlar soni: <b>{len(sorted_names)} ta</b>\n"
            msg += "═" * 22 + "\n\n"

            current_char = ""
            count = 1

            for name in sorted_names:
                first_char = name[0].upper()
                if first_char != current_char:
                    current_char = first_char
                    msg += f"\n🔤 <b>— [ {current_char} ] —</b>\n"

                info = active_debts[name]
                debt_str = f"{info['total_debt']:,.0f} so'm"
                phone_str = f" <i>({info['phone']})</i>" if info['phone'] else ""

                msg += (
                    f"<b>{count}. {name}</b>{phone_str}\n"
                    f"    └── 🔴 Qarz: <b>{debt_str}</b>\n"
                )
                count += 1

            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    # 6. ISHCHILAR OYLIGI
    elif text == "👨‍🔧 Ishchilar Oyligi":
        try:
            url = f"{SUPABASE_URL}/rest/v1/worker_salaries?select=date,amount,comment,workers(name,role)&order=id.desc&limit=8"
            res = requests.get(url, headers=HEADERS, timeout=10)
            salaries = res.json() if isinstance(res.json(), list) else []

            if not salaries:
                send_message(chat_id, "Oylik to'lovlari topilmadi.")
                return

            msg = "👨‍🔧 <b>Oxirgi Berilgan Oylik & Avanslar:</b>\n\n"
            for s in salaries:
                w_name = s.get("workers", {}).get("name") if s.get("workers") else "Ishchi"
                w_role = s.get("workers", {}).get("role", "") if s.get("workers") else ""
                msg += f"• [{s.get('date')}] <b>{w_name}</b> ({w_role}): -{float(s.get('amount') or 0):,.0f} so'm ({s.get('comment') or 'Oylik'})\n"
            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    # 7. BONUSLAR
    elif text == "🎁 Bonuslar Tahlili":
        try:
            url = f"{SUPABASE_URL}/rest/v1/production?select=quantity,total_bonus,has_bonus&has_bonus=eq.true"
            res = requests.get(url, headers=HEADERS, timeout=10)
            bonuses = res.json() if isinstance(res.json(), list) else []

            total_qop = sum(float(b.get("quantity") or 0) for b in bonuses)
            total_sum = sum(float(b.get("total_bonus") or 0) for b in bonuses)

            msg = (
                "🎁 <b>Bonuslar Umumiy Tahlili:</b>\n\n"
                f"🏷 Bonusli Qoplar: <b>{total_qop:,.0f} dona</b>\n"
                f"💸 Hisoblangan Bonus Puli: <b>{total_sum:,.0f} so'm</b>"
            )
            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    # 8. SANA YOZILGANDA (KASSA VA SOTUVNI BIRGALIKDA CHIQARISH)
    else:
        clean_text = text.strip()
        matched_date = None

        if re.match(r"^\d{4}-\d{2}-\d{2}$", clean_text):
            matched_date = clean_text
        elif re.match(r"^\d{2}\.\d{2}\.\d{4}$", clean_text):
            p = clean_text.split(".")
            matched_date = f"{p[2]}-{p[1]}-{p[0]}"

        if matched_date:
            # 1. Kassani olish
            k_rows = fetch_kassa_by_date(matched_date)
            k_msg = format_kassa_response(k_rows, f"💰 <b>{matched_date} KASSA HISOBOTI</b>")
            send_message(chat_id, k_msg)

            # 2. Sotuvlarni olish
            s_rows = fetch_sales_by_date(matched_date)
            s_msg = format_sales_response(s_rows, f"🗓 <b>{matched_date} SOTUV HISOBOTI</b>")
            send_message(chat_id, s_msg)
            return

        # 9. AGAR SANA BO'LMASA — MIJOZ QIDIRUVI
        try:
            query = clean_text.lower()
            active_debts = get_debts_dict()
            matched = {k: v for k, v in active_debts.items() if query in k.lower() or query in v["phone"]}

            if matched:
                msg = f"🔍 <b>'{clean_text}' bo'yicha qidiruv natijalari:</b>\n\n"
                for name, info in matched.items():
                    phone = f"\n📞 Tel: {info['phone']}" if info['phone'] else ""
                    msg += (
                        f"👤 <b>{name}</b>{phone}\n"
                        f"💰 Qarzdorlik: <b>{info['total_debt']:,.0f} so'm</b>\n"
                        f"────────────────────\n"
                    )
                send_message(chat_id, msg)
            else:
                send_message(
                    chat_id,
                    f"🔍 Hech narsa topilmadi.\n\n"
                    "• Qarzdor qidirish uchun ismini yozing (masalan: <code>Sfera</code>)\n"
                    "• Istalgan kun kassa/sotuvini ko'rish uchun sanani yozing (masalan: <code>2026-10-19</code>)",
                    reply_markup=MAIN_KEYBOARD,
                )
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN topilmadi!")
        return

    threading.Thread(target=start_dummy_server, daemon=True).start()
    logging.info(f"Render veb-porti ({PORT}) ochiq saqlanmoqda...")
    logging.info("Memor ERP boti ishga tushdi!")
    offset = 0

    while True:
        try:
            res = requests.get(
                f"{TELEGRAM_API}/getUpdates",
                params={"offset": offset, "timeout": 20},
                timeout=25,
            )
            data = res.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message")
                    if msg and "text" in msg:
                        chat_id = msg["chat"]["id"]
                        user_id = msg["from"]["id"]
                        text = msg["text"].strip()
                        first_name = msg["from"].get("first_name", "Foydalanuvchi")
                        handle_text(chat_id, user_id, text, first_name)
        except Exception as e:
            logging.error(f"Polling xatosi: {e}")
            time.sleep(3)

if __name__ == "__main__":
    main()
