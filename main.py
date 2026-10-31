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

MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "📦 Ombor Qoldig'i"}, {"text": "💰 Kassa Qoldig'i"}],
        [{"text": "👥 Mijozlar Qarzi"}, {"text": "📊 Kunlik Sotuvlar"}],
    ],
    "resize_keyboard": True,
}

# 1. Render portini ochiq ushlab turish uchun yengil veb-server
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

    def log_message(self, format, *args):
        pass  # Ortiqcha log chiqarmaslik uchun

def start_dummy_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
    server.serve_forever()

# 2. Telegram mantiqi
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
            f"Assalomu alaykum, <b>{first_name}</b>!\nMemor ERP boshqaruv botiga xush kelibsiz.",
            reply_markup=MAIN_KEYBOARD,
        )

    # Ombor
    elif text == "📦 Ombor Qoldig'i":
        try:
            url = f"{SUPABASE_URL}/rest/v1/materials?select=name,stock,unit"
            res = requests.get(url, headers=HEADERS, timeout=10)
            materials = res.json()
            if not isinstance(materials, list) or not materials:
                send_message(chat_id, "Omborda mahsulotlar topilmadi.")
                return

            msg = "📦 <b>Ombordagi mavjud qoldiqlar:</b>\n\n"
            for m in materials:
                msg += f"• <b>{m.get('name')}</b>: {m.get('stock')} {m.get('unit', '')}\n"
            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    # Kassa
    elif text == "💰 Kassa Qoldig'i":
        try:
            url = f"{SUPABASE_URL}/rest/v1/kassa?select=type,amount"
            res = requests.get(url, headers=HEADERS, timeout=10)
            rows = res.json()
            if not isinstance(rows, list):
                rows = []

            kirim = sum(float(r.get("amount") or 0) for r in rows if r.get("type") == "kirim")
            chiqim = sum(float(r.get("amount") or 0) for r in rows if r.get("type") == "chiqim")
            qoldiq = kirim - chiqim

            msg = (
                "💰 <b>Kassa Balansi:</b>\n\n"
                f"🟢 Jami Kirim: <b>{kirim:,.0f} so'm</b>\n"
                f"🔴 Jami Chiqim: <b>{chiqim:,.0f} so'm</b>\n"
                f"💵 Hozirgi Qoldiq: <b>{qoldiq:,.0f} so'm</b>"
            )
            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    # Qarzdorlik
    elif text == "👥 Mijozlar Qarzi":
        try:
            url = f"{SUPABASE_URL}/rest/v1/customer_sales?select=debt,customers(name)"
            res = requests.get(url, headers=HEADERS, timeout=10)
            rows = res.json()
            if not isinstance(rows, list):
                rows = []

            debts = {}
            for r in rows:
                c_name = r.get("customers", {}).get("name") if r.get("customers") else "Noma'lum"
                val = float(r.get("debt") or 0)
                debts[c_name] = debts.get(c_name, 0) + val

            active = {k: v for k, v in debts.items() if v > 0}
            if not active:
                send_message(chat_id, "Qarzdor mijozlar yo'q.")
                return

            msg = "👥 <b>Qarzdor mijozlar:</b>\n\n"
            for name, debt in sorted(active.items(), key=lambda x: x[1], reverse=True):
                msg += f"• <b>{name}</b>: {debt:,.0f} so'm\n"
            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

    # Sotuvlar
    elif text == "📊 Kunlik Sotuvlar":
        try:
            url = f"{SUPABASE_URL}/rest/v1/customer_sales?select=product_name,quantity,total,date&order=id.desc&limit=10"
            res = requests.get(url, headers=HEADERS, timeout=10)
            sales = res.json()
            if not isinstance(sales, list) or not sales:
                send_message(chat_id, "Sotuvlar topilmadi.")
                return

            msg = "📊 <b>Oxirgi 10 ta savdo:</b>\n\n"
            for s in sales:
                msg += f"• [{s.get('date')}] <b>{s.get('product_name')}</b> - {s.get('quantity')} dona ({float(s.get('total') or 0):,.0f} so'm)\n"
            send_message(chat_id, msg)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN topilmadi!")
        return

    # Render uchun alohida oqimda veb-portni yoqib qo'yamiz
    threading.Thread(target=start_dummy_server, daemon=True).start()
    logging.info(f"Render veb-porti ({PORT}) ochiq saqlanmoqda...")

    logging.info("Bot muvaffaqiyatli ishga tushdi!")
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
