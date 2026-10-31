import os
import time
import logging
import threading
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

# Saytdagi barcha 7 ta asosiy bo'lim tugmalari
MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "📦 Xomashyo & Qoplar"}, {"text": "🏭 Ostatka (Ishlab chiqarish)"}],
        [{"text": "💰 Kassa Balansi"}, {"text": "📒 Sotuv Daftari"}],
        [{"text": "👥 Qarzdor Mijozlar"}, {"text": "👨‍🔧 Ishchilar Oyligi"}],
        [{"text": "🎁 Bonuslar Tahlili"}],
    ],
    "resize_keyboard": True,
}

# Render veb-porti ochiq turishi uchun mini-server
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Memor ERP Bot is running perfectly!")

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

def handle_text(chat_id: int, user_id: int, text: str, first_name: str):
    if not is_admin(user_id):
        send_message(chat_id, f"Salom! Siz tizimda ro'yxatdan o'tmagansiz (Telegram ID: {user_id}).")
        return

    if text in ["/start", "start"]:
        send_message(
            chat_id,
            f"Assalomu alaykum, <b>{first_name}</b>!\n"
            "<b>Memor ERP</b> to'liq boshqaruv paneliga xush kelibsiz.\n"
            "Kerakli bo'limni tanlang:",
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

    # 2. OSTATKA & ISHLAB CHIQARISH
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
                "🏭 <b>Ostatka (Tayyor Mahsulot Zanjiri):</b>\n\n"
                f"🟢 Jami Ishlab Chiqarildi: <b>{jami_ishlab_chiqarildi:,.0f} qop</b>\n"
                f"🔴 Jami Sotildi / Chiqim: <b>{jami_sotildi:,.0f} qop</b>\n"
                f"📦 <b>Ombordagi Haqiqiy Qoldiq: {qoldiq_qop:,.0f} qop</b>"
            )
            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    # 3. KASSA BALANSI
    elif text == "💰 Kassa Balansi":
        try:
            url = f"{SUPABASE_URL}/rest/v1/kassa?select=type,amount"
            res = requests.get(url, headers=HEADERS, timeout=10)
            rows = res.json() if isinstance(res.json(), list) else []

            kirim = sum(float(r.get("amount") or 0) for r in rows if r.get("type") == "kirim")
            chiqim = sum(float(r.get("amount") or 0) for r in rows if r.get("type") == "chiqim")
            qoldiq = kirim - chiqim

            msg = (
                "💰 <b>Kassa & Balans:</b>\n\n"
                f"🟢 Jami Kirim: <b>{kirim:,.0f} so'm</b>\n"
                f"🔴 Jami Chiqim: <b>{chiqim:,.0f} so'm</b>\n"
                f"💵 <b>Hozirgi Kassa Qoldig'i: {qoldiq:,.0f} so'm</b>"
            )
            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    # 4. SOTUV DAFTARI
    elif text == "📒 Sotuv Daftari":
        try:
            url = f"{SUPABASE_URL}/rest/v1/customer_sales?select=product_name,quantity,price,total,paid,date,customers(name)&is_ostatka=eq.false&order=id.desc&limit=8"
            res = requests.get(url, headers=HEADERS, timeout=10)
            sales = res.json() if isinstance(res.json(), list) else []

            if not sales:
                send_message(chat_id, "Sotuv daftari bo'sh.")
                return

            msg = "📒 <b>Oxirgi Sotuvlar Jurnali:</b>\n\n"
            for s in sales:
                c_name = s.get("customers", {}).get("name") if s.get("customers") else "Mijoz"
                msg += (
                    f"🗓 <b>{s.get('date')}</b> | 👤 <b>{c_name}</b>\n"
                    f"📦 {s.get('product_name')}: {s.get('quantity')} ta = {float(s.get('total') or 0):,.0f} so'm\n"
                    f"💵 To'landi: {float(s.get('paid') or 0):,.0f} so'm\n"
                    f"--------------------\n"
                )
            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    # 5. QARZDOR MIJOZLAR
    elif text == "👥 Qarzdor Mijozlar":
        try:
            url = f"{SUPABASE_URL}/rest/v1/customer_sales?select=debt,customers(name,phone)"
            res = requests.get(url, headers=HEADERS, timeout=10)
            rows = res.json() if isinstance(res.json(), list) else []

            debts = {}
            for r in rows:
                c = r.get("customers")
                c_name = c.get("name") if c else "Noma'lum"
                val = float(r.get("debt") or 0)
                debts[c_name] = debts.get(c_name, 0) + val

            active = {k: v for k, v in debts.items() if v > 0}
            if not active:
                send_message(chat_id, "Hozirda qarzdor mijozlar yo'q.")
                return

            jami_qarz = sum(active.values())
            msg = f"👥 <b>Qarzdor Mijozlar Ro'yxati:</b>\n(Jami qarz: <b>{jami_qarz:,.0f} so'm</b>)\n\n"
            for name, debt in sorted(active.items(), key=lambda x: x[1], reverse=True):
                msg += f"• <b>{name}</b>: {debt:,.0f} so'm\n"
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

    # 7. BONUSLAR TAHLILI
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

def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN topilmadi!")
        return

    threading.Thread(target=start_dummy_server, daemon=True).start()
    logging.info(f"Render veb-porti ({PORT}) ochiq saqlanmoqda...")
    logging.info("Memor ERP to'liq boti ishga tushdi!")
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
