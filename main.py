import os
import time
import logging
import threading
from datetime import datetime, timezone, timedelta
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

# O'zbekiston vaqti (UTC+5)
UZ_TZ = timezone(timedelta(hours=5))

def get_uz_today() -> datetime:
    return datetime.now(UZ_TZ)

MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "📦 Xomashyo & Qoplar"}, {"text": "🏭 Ostatka (Ishlab chiqarish)"}],
        [{"text": "💰 Kassa Balansi"}, {"text": "📒 Sotuv Daftari"}],
        [{"text": "👥 Qarzdor Mijozlar"}, {"text": "👨‍🔧 Ishchilar Oyligi"}],
        [{"text": "🎁 Bonuslar Tahlili"}],
    ],
    "resize_keyboard": True,
}

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

def edit_message_text(chat_id: int, message_id: int, text: str, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Xabarni tahrirlashda xatolik: {e}")

# ----------------- INLINE TUGMALARNI GENERATSIYA QILISH -----------------
def generate_date_picker_keyboard(section_prefix: str, days_back: int = 7):
    buttons = []
    
    if section_prefix == "prod":
        buttons.append([{"text": "📊 Umumiy Ostatka Zanjiri", "callback_data": "prod_all"}])
    elif section_prefix == "kassa":
        buttons.append([{"text": "💵 Umumiy Kassa Balansi", "callback_data": "kassa_all"}])
    elif section_prefix == "sale":
        buttons.append([{"text": "📒 Oxirgi 10 ta Savdo", "callback_data": "sale_all"}])

    today = get_uz_today()
    yesterday = today - timedelta(days=1)
    
    t_str = today.strftime("%Y-%m-%d")
    y_str = yesterday.strftime("%Y-%m-%d")
    
    buttons.append([
        {"text": f"🟢 Bugun ({today.strftime('%d.%m')})", "callback_data": f"{section_prefix}_{t_str}"},
        {"text": f"🟡 Kecha ({yesterday.strftime('%d.%m')})", "callback_data": f"{section_prefix}_{y_str}"}
    ])

    row = []
    for i in range(2, days_back + 1):
        day = today - timedelta(days=i)
        d_str = day.strftime("%Y-%m-%d")
        d_label = day.strftime("%d-%b")
        row.append({"text": f"🗓 {d_label}", "callback_data": f"{section_prefix}_{d_str}"})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    return {"inline_keyboard": buttons}

# ----------------- SANANI FILTRLASH YORDAMCHISI -----------------
def check_row_date(row: dict, target_date: str) -> bool:
    """Qatorda date yoki created_at ustunlaridan biri berilgan sanaga to'g'ri keladimi tekshiradi"""
    for key in ["date", "created_at", "sana"]:
        val = str(row.get(key) or "")
        if val.startswith(target_date):
            return True
    return False

# ----------------- 1. OSTATKA / ISHLAB CHIQARISH -----------------
def get_production_report(date_str: str = None):
    p_res = requests.get(f"{SUPABASE_URL}/rest/v1/production?select=*", headers=HEADERS, timeout=10)
    s_res = requests.get(f"{SUPABASE_URL}/rest/v1/customer_sales?select=*&is_ostatka=eq.false", headers=HEADERS, timeout=10)

    p_data = p_res.json() if isinstance(p_res.json(), list) else []
    s_data = s_res.json() if isinstance(s_res.json(), list) else []

    if not date_str:
        jami_ishlab_chiqarildi = sum(float(x.get("quantity") or 0) for x in p_data)
        jami_sotildi = sum(float(x.get("quantity") or 0) for x in s_data)
        qoldiq_qop = max(0, jami_ishlab_chiqarildi - jami_sotildi)

        msg = (
            "🏭 <b>Umumiy Ostatka (Ishlab chiqarish balansi):</b>\n\n"
            f"🟢 Jami Ishlab Chiqarildi: <b>{jami_ishlab_chiqarildi:,.0f} qop</b>\n"
            f"🔴 Jami Sotildi / Chiqim: <b>{jami_sotildi:,.0f} qop</b>\n"
            f"📦 <b>Ombordagi Haqiqiy Qoldiq: {qoldiq_qop:,.0f} qop</b>"
        )
        return msg

    filtered_prods = [x for x in p_data if check_row_date(x, date_str)]

    if not filtered_prods:
        return f"🏭 <b>{date_str}</b> sanasida ishlab chiqarish ma'lumotlari topilmadi."

    total_bags = sum(float(x.get("quantity") or 0) for x in filtered_prods)
    msg = f"🏭 <b>{date_str} sanasidagi Ishlab Chiqarish:</b>\n"
    msg += f"📦 Jami tayyorlangan: <b>{total_bags:,.0f} qop</b>\n"
    msg += "═" * 22 + "\n\n"

    for i, p in enumerate(filtered_prods, 1):
        name = p.get("product_name") or p.get("name") or "Mahsulot"
        qty = float(p.get("quantity") or 0)
        bonus_mark = " 🎁 (Bonusli)" if p.get("has_bonus") else ""
        shift = f" [Smena: {p.get('shift')}]" if p.get("shift") else ""
        msg += f"{i}. <b>{name}</b>: {qty:,.0f} qop{bonus_mark}{shift}\n"

    return msg

# ----------------- 2. KASSA -----------------
def get_kassa_report(date_str: str = None):
    url = f"{SUPABASE_URL}/rest/v1/kassa?select=*"
    res = requests.get(url, headers=HEADERS, timeout=10)
    all_rows = res.json() if isinstance(res.json(), list) else []

    if not date_str:
        kirim = sum(float(r.get("amount") or 0) for r in all_rows if str(r.get("type", "")).lower() == "kirim")
        chiqim = sum(float(r.get("amount") or 0) for r in all_rows if str(r.get("type", "")).lower() == "chiqim")
        qoldiq = kirim - chiqim

        msg = (
            "💰 <b>Umumiy Kassa Balansi:</b>\n\n"
            f"🟢 Jami Kirim: <b>{kirim:,.0f} so'm</b>\n"
            f"🔴 Jami Chiqim: <b>{chiqim:,.0f} so'm</b>\n"
            f"💵 <b>Hozirgi Sof Qoldiq: {qoldiq:,.0f} so'm</b>"
        )
        return msg

    filtered_rows = [r for r in all_rows if check_row_date(r, date_str)]

    kirim = sum(float(r.get("amount") or 0) for r in filtered_rows if str(r.get("type", "")).lower() == "kirim")
    chiqim = sum(float(r.get("amount") or 0) for r in filtered_rows if str(r.get("type", "")).lower() == "chiqim")
    sof = kirim - chiqim

    msg = f"💰 <b>{date_str} Kassa Hisoboti:</b>\n\n"
    msg += f"🟢 Kirim: <b>+{kirim:,.0f} so'm</b>\n"
    msg += f"🔴 Chiqim: <b>-{chiqim:,.0f} so'm</b>\n"
    msg += f"💵 Kunlik sof qoldiq: <b>{sof:,.0f} so'm</b>\n"
    msg += "═" * 22 + "\n\n"

    if not filtered_rows:
        msg += "<i>Ushbu sanada kassa harakatlari amalga oshirilmagan.</i>"
        return msg

    for i, r in enumerate(filtered_rows, 1):
        is_kirim = str(r.get("type", "")).lower() == "kirim"
        t = "🟢 Kirim" if is_kirim else "🔴 Chiqim"
        comm = r.get("comment") or r.get("category") or "Izohsiz"
        msg += f"{i}. {t}: <b>{float(r.get('amount') or 0):,.0f} so'm</b>\n   └ <i>{comm}</i>\n"

    return msg

# ----------------- 3. SOTUV DAFTARI -----------------
def get_sales_report(date_str: str = None):
    url = f"{SUPABASE_URL}/rest/v1/customer_sales?select=*,customers(name)&is_ostatka=eq.false&order=id.desc"
    res = requests.get(url, headers=HEADERS, timeout=10)
    all_sales = res.json() if isinstance(res.json(), list) else []

    if not date_str:
        sales = all_sales[:10]
        title = "📒 <b>Oxirgi 10 ta Savdo Jurnali:</b>"
    else:
        sales = [s for s in all_sales if check_row_date(s, date_str)]
        title = f"🗓 <b>{date_str} Sanasidagi Sotuvlar:</b>"

    if not sales:
        return f"{title}\n\n<i>Sotuvlar topilmadi.</i>"

    tot_sum = sum(float(s.get("total") or 0) for s in sales)
    tot_qty = sum(float(s.get("quantity") or 0) for s in sales)

    msg = f"{title}\n"
    msg += f"📦 Jami hajm: <b>{tot_qty:,.0f} dona</b>\n"
    msg += f"💵 Jami summa: <b>{tot_sum:,.0f} so'm</b>\n"
    msg += "═" * 22 + "\n\n"

    for i, s in enumerate(sales, 1):
        c_name = s.get("customers", {}).get("name") if s.get("customers") else (s.get("customer_name") or "Mijoz")
        p_name = s.get("product_name") or "Mahsulot"
        msg += f"<b>{i}. {c_name}</b> | {p_name}: {s.get('quantity')} ta ({float(s.get('total') or 0):,.0f} so'm)\n"

    return msg

# ----------------- 4. QARZDORLAR -----------------
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

# ----------------- CALLBACK TUGMALARNI QAYTA ISHLASH -----------------
def handle_callback_query(callback_id: str, chat_id: int, message_id: int, data: str):
    try:
        requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": callback_id}, timeout=5)
    except:
        pass

    if data.startswith("prod_"):
        val = data.replace("prod_", "")
        date_param = None if val == "all" else val
        text = get_production_report(date_param)
        edit_message_text(chat_id, message_id, text, reply_markup=generate_date_picker_keyboard("prod"))

    elif data.startswith("kassa_"):
        val = data.replace("kassa_", "")
        date_param = None if val == "all" else val
        text = get_kassa_report(date_param)
        edit_message_text(chat_id, message_id, text, reply_markup=generate_date_picker_keyboard("kassa"))

    elif data.startswith("sale_"):
        val = data.replace("sale_", "")
        date_param = None if val == "all" else val
        text = get_sales_report(date_param)
        edit_message_text(chat_id, message_id, text, reply_markup=generate_date_picker_keyboard("sale"))

# ----------------- XABARLARNI QAYTA ISHLASH -----------------
def handle_text(chat_id: int, user_id: int, text: str, first_name: str):
    if not is_admin(user_id):
        send_message(chat_id, f"Salom! Siz tizimda ro'yxatdan o'tmagansiz (Telegram ID: {user_id}).")
        return

    if text in ["/start", "start"]:
        send_message(
            chat_id,
            f"Assalomu alaykum, <b>{first_name}</b>!\n"
            "Memor ERP boshqaruv paneliga xush kelibsiz.\n"
            "Bo'limni tanlang:",
            reply_markup=MAIN_KEYBOARD,
        )

    elif text == "📦 Xomashyo & Qoplar":
        try:
            url = f"{SUPABASE_URL}/rest/v1/materials?select=name,stock,unit&order=name.asc"
            res = requests.get(url, headers=HEADERS, timeout=10)
            materials = res.json() if isinstance(res.json(), list) else []
            if not materials:
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

    elif text == "🏭 Ostatka (Ishlab chiqarish)":
        msg = get_production_report(None)
        kb = generate_date_picker_keyboard("prod")
        send_message(chat_id, msg, reply_markup=kb)

    elif text == "💰 Kassa Balansi":
        msg = get_kassa_report(None)
        kb = generate_date_picker_keyboard("kassa")
        send_message(chat_id, msg, reply_markup=kb)

    elif text == "📒 Sotuv Daftari":
        msg = get_sales_report(None)
        kb = generate_date_picker_keyboard("sale")
        send_message(chat_id, msg, reply_markup=kb)

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

    else:
        try:
            query = text.strip().lower()
            active_debts = get_debts_dict()
            matched = {k: v for k, v in active_debts.items() if query in k.lower() or query in v["phone"]}

            if matched:
                msg = f"🔍 <b>'{text}' bo'yicha qidiruv:</b>\n\n"
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
                    f"🔍 '{text}' bo'yicha ma'lumot topilmadi.\nKerakli bo'limni tanlang:",
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
                    
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        handle_callback_query(
                            cb["id"],
                            cb["message"]["chat"]["id"],
                            cb["message"]["message_id"],
                            cb["data"],
                        )

                    elif "message" in update and "text" in update["message"]:
                        msg = update["message"]
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
