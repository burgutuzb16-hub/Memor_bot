import os
import time
import re
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

UZ_TZ = timezone(timedelta(hours=5))
OSTATKA_START_DATE = "2026-11-01"

def get_uz_today() -> datetime:
    return datetime.now(UZ_TZ)

MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "🏭 Ostatka (Retseptlar)"}, {"text": "📦 Xomashyo & Qoplar"}],
        [{"text": "💰 Kassa Balansi"}, {"text": "📒 Sotuv Daftari"}],
        [{"text": "👨‍🔧 Ishchilar Oyligi"}, {"text": "👥 Qarzdor Mijozlar"}],
        [{"text": "🏢 Korxonani Almashtirish"}, {"text": "🎁 Bonuslar"}],
    ],
    "resize_keyboard": True,
}

# Foydalanuvchining joriy tanlagan korxonasi (chat_id -> branch_id)
USER_ACTIVE_BRANCH = {}

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
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Xabar yuborishda xatolik: {e}")

def edit_message_text(chat_id: int, message_id: int, text: str, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Tahrirlashda xatolik: {e}")

def clean_name(str_val: str) -> str:
    if not str_val:
        return ""
    return re.sub(r"^[+\-*_]+", "", str_val.split("(")[0]).strip().lower()

def get_current_branch(chat_id: int):
    # Agar tanlanmagan bo'lsa, birinchi korxonani oladi
    b_id = USER_ACTIVE_BRANCH.get(chat_id)
    b_res = requests.get(f"{SUPABASE_URL}/rest/v1/branches?select=*&order=id.asc", headers=HEADERS, timeout=10)
    branches = b_res.json() if isinstance(b_res.json(), list) else []
    if not branches:
        return None, "Korxonalar mavjud emas"

    if not b_id or not any(b.get("id") == b_id for b in branches):
        b_id = branches[0].get("id")
        USER_ACTIVE_BRANCH[chat_id] = b_id

    curr = next((b for b in branches if b.get("id") == b_id), branches[0])
    return curr.get("id"), f"{curr.get('name')} ({curr.get('city')})"

# ----------------- KORXONANI TANLASH -----------------
def get_branch_selector_keyboard():
    b_res = requests.get(f"{SUPABASE_URL}/rest/v1/branches?select=*&order=id.asc", headers=HEADERS, timeout=10)
    branches = b_res.json() if isinstance(b_res.json(), list) else []
    buttons = []
    for b in branches:
        buttons.append([{"text": f"🏢 {b.get('name')} ({b.get('city')})", "callback_data": f"set_br_{b.get('id')}"}])
    return "🏢 <b>Kerakli korxonani tanlang:</b>", {"inline_keyboard": buttons}

# ----------------- 1. OSTATKA (RETSEPTLAR) -----------------
def get_production_report(chat_id: int):
    b_id, b_name = get_current_branch(chat_id)
    if not b_id:
        return "Korxona topilmadi."

    # Sotuvlar (01.11.2026 dan)
    s_url = f"{SUPABASE_URL}/rest/v1/customer_sales?select=product_name,quantity&is_ostatka=eq.false&date=gte.{OSTATKA_START_DATE}"
    s_res = requests.get(s_url, headers=HEADERS, timeout=10)
    sales = s_res.json() if isinstance(s_res.json(), list) else []

    sold_map = {}
    for s in sales:
        c_name = clean_name(s.get("product_name"))
        q = float(s.get("quantity") or 0)
        if c_name:
            sold_map[c_name] = sold_map.get(c_name, 0.0) + q

    # Ishlab chiqarish
    p_url = f"{SUPABASE_URL}/rest/v1/production?select=*&branch_id=eq.{b_id}&date=gte.{OSTATKA_START_DATE}"
    p_res = requests.get(p_url, headers=HEADERS, timeout=10)
    prods = p_res.json() if isinstance(p_res.json(), list) else []

    prod_map = {}
    tot_p = 0
    for p in prods:
        c_name = clean_name(p.get("recipe_name"))
        q = float(p.get("quantity") or 0)
        if c_name:
            prod_map[c_name] = prod_map.get(c_name, 0.0) + q
            tot_p += q

    r_res = requests.get(f"{SUPABASE_URL}/rest/v1/recipes?select=name", headers=HEADERS, timeout=10)
    recipes = r_res.json() if isinstance(r_res.json(), list) else []

    all_keys = sorted(list(set(list(prod_map.keys()) + [clean_name(r.get("name")) for r in recipes])))

    msg = f"🏭 <b>{b_name} — OSTATKA</b>\n"
    msg += f"<i>(01.11.2026 dan boshlab)</i>\n"
    msg += f"🟢 Ishlab chiqarildi: <b>{tot_p:,.0f} qop</b>\n\n"

    total_real = 0
    for k in all_keys:
        if not k:
            continue
        p_q = prod_map.get(k, 0.0)
        s_q = sold_map.get(k, 0.0)
        bal = max(0.0, p_q - s_q)
        total_real += bal
        icon = "🟢" if bal > 50 else ("🟡" if bal > 0 else "🔴")
        msg += f"{icon} <b>{k.upper()}</b>:\n"
        msg += f"   • Ishlab chiqarildi: +{p_q:,.0f} qop\n"
        msg += f"   • Sotildi: -{s_q:,.0f} qop\n"
        msg += f"   👉 <b>Qoldiq: {bal:,.0f} qop</b>\n\n"

    msg += f"📦 <b>Ombordagi Aniq Qoldiq: {total_real:,.0f} qop</b>"
    return msg

# ----------------- 2. XOMASHYO -----------------
def get_materials_report(chat_id: int):
    b_id, b_name = get_current_branch(chat_id)
    url = f"{SUPABASE_URL}/rest/v1/materials?select=*&branch_id=eq.{b_id}&order=name.asc"
    res = requests.get(url, headers=HEADERS, timeout=10)
    materials = res.json() if isinstance(res.json(), list) else []

    if not materials:
        return f"📦 <b>{b_name}</b> omborida materiallar mavjud emas."

    msg = f"📦 <b>{b_name} — Xomashyo & Qoplar:</b>\n\n"
    for m in materials:
        name = m.get("name") or "Material"
        stock = float(m.get("stock") or 0)
        unit = m.get("unit") or "dona"
        icon = "🟡" if "qop" in name.lower() else "🔹"
        msg += f"{icon} <b>{name}</b>: <b>{stock:,.0f} {unit}</b>\n"
    return msg

# ----------------- 3. KASSA -----------------
def get_kassa_report(chat_id: int):
    b_id, b_name = get_current_branch(chat_id)
    url = f"{SUPABASE_URL}/rest/v1/kassa?select=*&branch_id=eq.{b_id}&order=date.asc"
    res = requests.get(url, headers=HEADERS, timeout=10)
    rows = res.json() if isinstance(res.json(), list) else []

    kirim = sum(float(r.get("amount") or 0) for r in rows if str(r.get("type", "")).lower() == "kirim")
    chiqim = sum(float(r.get("amount") or 0) for r in rows if str(r.get("type", "")).lower() == "chiqim")
    qoldiq = kirim - chiqim

    today_str = get_uz_today().strftime("%Y-%m-%d")
    today_rows = [r for r in rows if str(r.get("date") or "")[:10] == today_str]
    t_k = sum(float(r.get("amount") or 0) for r in today_rows if str(r.get("type", "")).lower() == "kirim")
    t_ch = sum(float(r.get("amount") or 0) for r in today_rows if str(r.get("type", "")).lower() == "chiqim")

    msg = (
        f"💰 <b>{b_name} — KASSA</b>\n\n"
        f"🟢 Jami Kirim: <b>+{kirim:,.0f} so'm</b>\n"
        f"🔴 Jami Chiqim: <b>-{chiqim:,.0f} so'm</b>\n"
        f"💵 <b>Sof Kassa Qoldig'i: {qoldiq:,.0f} so'm</b>\n\n"
        f"🗓 <b>Bugun ({today_str}):</b>\n"
        f"• Kirim: +{t_k:,.0f} | Chiqim: -{t_ch:,.0f}\n"
        f"• Sof aylanma: <b>{t_k - t_ch:+,.0f} so'm</b>"
    )
    return msg

# ----------------- 4. SOTUV DAFTARI -----------------
def get_sales_report():
    url = f"{SUPABASE_URL}/rest/v1/customer_sales?select=*,customers(name)&is_ostatka=eq.false&order=id.desc&limit=8"
    res = requests.get(url, headers=HEADERS, timeout=10)
    sales = res.json() if isinstance(res.json(), list) else []

    if not sales:
        return "📒 <i>Sotuvlar daftari bo'sh.</i>"

    msg = "📒 <b>Oxirgi Sotuvlar Jurnali:</b>\n\n"
    for i, s in enumerate(sales, 1):
        c_name = s.get("customers", {}).get("name") if s.get("customers") else "Mijoz"
        p_name = s.get("product_name") or "Mahsulot"
        qty = s.get("quantity") or 0
        total = float(s.get("total") or 0)
        s_date = str(s.get("date") or "")[:10]
        msg += f"<b>{i}. {c_name}</b> ({s_date})\n"
        msg += f"   └ {p_name} × {qty} ta = <b>{total:,.0f} so'm</b>\n"
    return msg

# ----------------- 5. ISHCHILAR OYLIGI (TARTIBLI & IXCHAM) -----------------
def get_worker_months_keyboard():
    months = ["2026-11", "2026-10", "2026-09"]
    cur_m = get_uz_today().strftime("%Y-%m")
    if cur_m not in months:
        months.insert(0, cur_m)

    buttons = []
    for m in months:
        buttons.append([{"text": f"📅 {m} Oyi Maoshlari", "callback_data": f"wm_{m}"}])

    return "👨‍🔧 <b>Ishchilar Oyligi Arxivlari:</b>\nQaysi oyni ko'rmoqchisiz?", {"inline_keyboard": buttons}

def get_worker_monthly_report(chat_id: int, m_str: str):
    b_id, b_name = get_current_branch(chat_id)

    w_res = requests.get(f"{SUPABASE_URL}/rest/v1/workers?select=*&branch_id=eq.{b_id}&order=name.asc", headers=HEADERS, timeout=10)
    workers = w_res.json() if isinstance(w_res.json(), list) else []

    sett_res = requests.get(f"{SUPABASE_URL}/rest/v1/worker_monthly_settlements?month=eq.{m_str}&branch_id=eq.{b_id}", headers=HEADERS, timeout=10)
    settlements = sett_res.json() if isinstance(sett_res.json(), list) else []
    sett_map = {s.get("worker_id"): s for s in settlements}

    sal_res = requests.get(f"{SUPABASE_URL}/rest/v1/worker_salaries?select=*&branch_id=eq.{b_id}&date=gte.{m_str}-01&date=lte.{m_str}-31", headers=HEADERS, timeout=10)
    salaries = sal_res.json() if isinstance(sal_res.json(), list) else []

    p_res = requests.get(f"{SUPABASE_URL}/rest/v1/production?select=quantity&branch_id=eq.{b_id}&date=gte.{m_str}-01&date=lte.{m_str}-31", headers=HEADERS, timeout=10)
    prods = p_res.json() if isinstance(p_res.json(), list) else []
    factory_total_bags = sum(float(p.get("quantity") or 0) for p in prods)

    if not workers:
        return f"👨‍🔧 <b>{b_name}</b>da ishchilar ro'yxati topilmadi.", {"inline_keyboard": [[{"text": "🔙 Ortga", "callback_data": "wm_back"}]]}

    tot_earned = 0
    tot_advances = 0

    msg = f"👨‍🔧 <b>{b_name}</b>\n"
    msg += f"📅 <b>{m_str} Oyi Hisoboti:</b>\n"
    msg += f"🏭 Ishlab chiqarildi: <b>{factory_total_bags:,.0f} qop</b>\n"
    msg += "────────────────────────\n\n"

    for i, w in enumerate(workers, 1):
        w_id = w.get("id")
        w_name = w.get("name") or "Ishchi"
        is_piece = (w.get("salary_type") or "piecework") == "piecework"

        sett = sett_map.get(w_id, {})
        p_qty = float(sett.get("produced_qty") or 0)
        rate = float(sett.get("rate") or w.get("rate") or 0)

        total_salary = (p_qty * rate) if is_piece else rate
        advances = sum(float(s.get("amount") or 0) for s in salaries if s.get("worker_id") == w_id)
        rem_debt = total_salary - advances

        tot_earned += total_salary
        tot_advances += advances

        msg += f"<b>{i}. {w_name}</b>\n"
        if is_piece:
            msg += f"   • Ishlagan: <b>{p_qty:,.0f} qop</b> ({rate:,.0f} so'mdan)\n"
        msg += f"   • Maosh: <b>{total_salary:,.0f} so'm</b>\n"
        msg += f"   • Avans: <b>-{advances:,.0f} so'm</b>\n"
        msg += f"   👉 <b>Qoldiq: {rem_debt:,.0f} so'm</b>\n\n"

    msg += "────────────────────────\n"
    msg += f"📊 <b>OY YAKUNI:</b>\n"
    msg += f"• Jami Maosh: <b>{tot_earned:,.0f} so'm</b>\n"
    msg += f"• To'langan: <b>{tot_advances:,.0f} so'm</b>\n"
    msg += f"• Korxona Qarzi: <b>{tot_earned - tot_advances:,.0f} so'm</b>"

    kb = {"inline_keyboard": [[{"text": "🔙 Boshqa oyni tanlash", "callback_data": "wm_back"}]]}
    return msg, kb

# ----------------- 6. QARZDORLAR -----------------
def get_debts_structure():
    url = f"{SUPABASE_URL}/rest/v1/customer_sales?select=debt,customers(name,phone,folder)"
    res = requests.get(url, headers=HEADERS, timeout=10)
    rows = res.json() if isinstance(res.json(), list) else []

    regions = {}
    for r in rows:
        c = r.get("customers")
        if not c:
            continue
        c_name = (c.get("name") or "Noma'lum").strip()
        folder = (c.get("folder") or "Umumiy").strip().title()
        phone = (c.get("phone") or "").strip()
        debt_val = float(r.get("debt") or 0)

        if folder not in regions:
            regions[folder] = {}
        if c_name not in regions[folder]:
            regions[folder][c_name] = {"debt": 0.0, "phone": phone}
        regions[folder][c_name]["debt"] += debt_val

    active_regions = {}
    for f, clients in regions.items():
        act = {name: data for name, data in clients.items() if data["debt"] > 0}
        if act:
            active_regions[f] = act
    return active_regions

def get_region_keyboard():
    regions = get_debts_structure()
    buttons = []
    total_all = sum(sum(c["debt"] for c in cl.values()) for cl in regions.values())

    row = []
    for reg_name in sorted(regions.keys()):
        row.append({"text": f"📁 {reg_name}", "callback_data": f"debts_reg_{reg_name}"})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    text = f"👥 <b>Qarzdor Mijozlar:</b>\n💵 Jami Qarz: <b>{total_all:,.0f} so'm</b>\n\nHududni tanlang:"
    return text, {"inline_keyboard": buttons}

# ----------------- 7. BONUSLAR -----------------
def get_bonus_report():
    url = f"{SUPABASE_URL}/rest/v1/production?select=quantity,total_bonus,has_bonus&has_bonus=eq.true"
    res = requests.get(url, headers=HEADERS, timeout=10)
    bonuses = res.json() if isinstance(res.json(), list) else []

    total_qop = sum(float(b.get("quantity") or 0) for b in bonuses)
    total_sum = sum(float(b.get("total_bonus") or 0) for b in bonuses)

    return (
        "🎁 <b>Bonuslar Tahlili:</b>\n\n"
        f"🏷 Bonusli Qoplar: <b>{total_qop:,.0f} dona</b>\n"
        f"💸 Sarflangan Mablag': <b>{total_sum:,.0f} so'm</b>"
    )

# ----------------- CALLBACK TUGMALAR -----------------
def handle_callback_query(callback_id: str, chat_id: int, message_id: int, data: str):
    try:
        requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": callback_id}, timeout=5)
    except:
        pass

    # Korxona tanlash
    if data.startswith("set_br_"):
        b_id = int(data.replace("set_br_", ""))
        USER_ACTIVE_BRANCH[chat_id] = b_id
        _, b_name = get_current_branch(chat_id)
        edit_message_text(chat_id, message_id, f"✅ <b>Faol korxona tanlandi:</b>\n🏢 {b_name}\n\nEndi barcha ma'lumotlar faqat shu korxona bo'yicha ko'rsatiladi.")
        return

    # Ishchilar oyligi
    if data == "wm_back":
        text, kb = get_worker_months_keyboard()
        edit_message_text(chat_id, message_id, text, reply_markup=kb)
        return

    if data.startswith("wm_"):
        m_str = data.replace("wm_", "")
        text, kb = get_worker_monthly_report(chat_id, m_str)
        edit_message_text(chat_id, message_id, text, reply_markup=kb)
        return

    # Qarzdorlar
    if data == "debts_back_regions":
        text, kb = get_region_keyboard()
        edit_message_text(chat_id, message_id, text, reply_markup=kb)
        return

    if data.startswith("debts_reg_"):
        reg = data.replace("debts_reg_", "")
        regions = get_debts_structure()
        clients = regions.get(reg, {})
        buttons = []
        for c_name in sorted(clients.keys(), key=lambda s: s.lower()):
            d_val = clients[c_name]["debt"]
            buttons.append([{"text": f"👤 {c_name} — {d_val:,.0f}", "callback_data": f"debts_cl_{reg}_{c_name}"}])
        buttons.append([{"text": "🔙 Boshqa hudud", "callback_data": "debts_back_regions"}])
        edit_message_text(chat_id, message_id, f"📁 <b>{reg} hududi:</b>\nMijozni tanlang:", reply_markup={"inline_keyboard": buttons})
        return

    if data.startswith("debts_cl_"):
        parts = data.replace("debts_cl_", "").split("_", 1)
        reg, cl_name = parts[0], parts[1]
        regions = get_debts_structure()
        cl_info = regions.get(reg, {}).get(cl_name, {})
        phone_str = f"\n📞 Tel: <b>{cl_info.get('phone')}</b>" if cl_info.get("phone") else ""
        msg = (
            f"👤 <b>MIJOZ QARZ KARTASI:</b>\n\n"
            f"📌 Ism: <b>{cl_name}</b>\n"
            f"📍 Hudud: <b>{reg}</b>{phone_str}\n"
            f"💰 Qarz: <b>{cl_info.get('debt', 0):,.0f} so'm</b>"
        )
        kb = {"inline_keyboard": [[{"text": f"🔙 {reg} ro'yxatiga qaytish", "callback_data": f"debts_reg_{reg}"}]]}
        edit_message_text(chat_id, message_id, msg, reply_markup=kb)
        return

# ----------------- ASOSIY BUYRUQLAR -----------------
def handle_text(chat_id: int, user_id: int, text: str, first_name: str):
    if not is_admin(user_id):
        send_message(chat_id, f"Salom! Siz ro'yxatdan o'tmagansiz (Telegram ID: {user_id}).")
        return

    clean_text = text.strip()
    _, b_name = get_current_branch(chat_id)

    if clean_text in ["/start", "start"]:
        send_message(
            chat_id,
            f"Assalomu alaykum, <b>{first_name}</b>!\n"
            f"🏢 Hozirgi tanlangan korxona: <b>{b_name}</b>\n\n"
            "Kerakli bo'limni tanlang:",
            reply_markup=MAIN_KEYBOARD,
        )

    elif clean_text == "🏢 Korxonani Almashtirish":
        text_b, kb_b = get_branch_selector_keyboard()
        send_message(chat_id, text_b, reply_markup=kb_b)

    elif clean_text == "🏭 Ostatka (Retseptlar)":
        send_message(chat_id, get_production_report(chat_id))

    elif clean_text == "📦 Xomashyo & Qoplar":
        send_message(chat_id, get_materials_report(chat_id))

    elif clean_text == "💰 Kassa Balansi":
        send_message(chat_id, get_kassa_report(chat_id))

    elif clean_text == "📒 Sotuv Daftari":
        send_message(chat_id, get_sales_report())

    elif clean_text == "👨‍🔧 Ishchilar Oyligi":
        text_m, kb_m = get_worker_months_keyboard()
        send_message(chat_id, text_m, reply_markup=kb_m)

    elif clean_text == "👥 Qarzdor Mijozlar":
        text_reg, kb_reg = get_region_keyboard()
        send_message(chat_id, text_reg, reply_markup=kb_reg)

    elif clean_text == "🎁 Bonuslar":
        send_message(chat_id, get_bonus_report())

    else:
        # Mijoz qidiruvi
        try:
            query = clean_text.lower()
            regions = get_debts_structure()
            matched = []
            for reg, cl in regions.items():
                for name, info in cl.items():
                    if query in name.lower() or query in info["phone"]:
                        matched.append((reg, name, info))

            if matched:
                msg = f"🔍 <b>'{clean_text}' bo'yicha topildi:</b>\n\n"
                for reg, name, info in matched:
                    phone = f"\n📞 Tel: {info['phone']}" if info['phone'] else ""
                    msg += f"👤 <b>{name}</b> (📍 {reg}){phone}\n💰 Qarz: <b>{info['debt']:,.0f} so'm</b>\n──────────────\n"
                send_message(chat_id, msg)
            else:
                send_message(chat_id, f"🔍 '{clean_text}' topilmadi.", reply_markup=MAIN_KEYBOARD)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN topilmadi!")
        return

    threading.Thread(target=start_dummy_server, daemon=True).start()
    logging.info("Memor ERP boti ishga tushdi!")
    offset = 0

    while True:
        try:
            res = requests.get(f"{TELEGRAM_API}/getUpdates", params={"offset": offset, "timeout": 20}, timeout=25)
            data = res.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        handle_callback_query(cb["id"], cb["message"]["chat"]["id"], cb["message"]["message_id"], cb["data"])
                    elif "message" in update and "text" in update["message"]:
                        msg = update["message"]
                        handle_text(msg["chat"]["id"], msg["from"]["id"], msg["text"].strip(), msg["from"].get("first_name", "Admin"))
        except Exception as e:
            logging.error(f"Polling xatosi: {e}")
            time.sleep(3)

if __name__ == "__main__":
    main()


