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
        [{"text": "🏭 Korxonalar & Ostatka"}, {"text": "📦 Xomashyo & Qoplar"}],
        [{"text": "💰 Kassa Balansi"}, {"text": "📒 Sotuv Daftari"}],
        [{"text": "👥 Qarzdor Mijozlar"}, {"text": "👨‍🔧 Ishchilar Oyligi (Arxiv)"}],
        [{"text": "🎁 Bonuslar Tahlili"}],
    ],
    "resize_keyboard": True,
}

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

# ----------------- 1. KORXONALAR VA OSTATKA (RETSEPTLAR BALANSI) -----------------
def get_enterprises_report():
    b_res = requests.get(f"{SUPABASE_URL}/rest/v1/branches?select=*&order=id.asc", headers=HEADERS, timeout=10)
    branches = b_res.json() if isinstance(b_res.json(), list) else []

    if not branches:
        return "🏢 Tizimda korxonalar topilmadi.", None

    buttons = []
    for b in branches:
        buttons.append([{"text": f"🏢 {b.get('name')} ({b.get('city')})", "callback_data": f"branch_ost_{b.get('id')}"}])
    buttons.append([{"text": "📊 Barcha Korxonalar Umumiy Balansi", "callback_data": "branch_ost_all"}])

    msg = "🏢 <b>Korxonalar Ostatkasi:</b>\nQaysi korxona bo'yicha mahsulot qoldiqlarini ko'rmoqchisiz?"
    return msg, {"inline_keyboard": buttons}

def get_production_breakdown(branch_id=None):
    # 01.11.2026 dan keyingi sotuvlar
    s_url = f"{SUPABASE_URL}/rest/v1/customer_sales?select=product_name,quantity,date&is_ostatka=eq.false&date=gte.{OSTATKA_START_DATE}"
    s_res = requests.get(s_url, headers=HEADERS, timeout=10)
    sales = s_res.json() if isinstance(s_res.json(), list) else []

    sold_map = {}
    total_sold = 0
    for s in sales:
        c_name = clean_name(s.get("product_name"))
        q = float(s.get("quantity") or 0)
        if c_name:
            sold_map[c_name] = sold_map.get(c_name, 0.0) + q
            total_sold += q

    # 01.11.2026 dan keyingi ishlab chiqarish
    p_url = f"{SUPABASE_URL}/rest/v1/production?select=*&date=gte.{OSTATKA_START_DATE}&order=date.desc"
    if branch_id and branch_id != "all":
        p_url += f"&branch_id=eq.{branch_id}"
    p_res = requests.get(p_url, headers=HEADERS, timeout=10)
    prods = p_res.json() if isinstance(p_res.json(), list) else []

    # Korxona nomi
    b_title = "Barcha Korxonalar (Umumiy)"
    if branch_id and branch_id != "all":
        br_res = requests.get(f"{SUPABASE_URL}/rest/v1/branches?id=eq.{branch_id}", headers=HEADERS, timeout=10)
        br_data = br_res.json() if isinstance(br_res.json(), list) else []
        if br_data:
            b_title = f"{br_data[0].get('name')} ({br_data[0].get('city')})"

    prod_map = {}
    total_produced = 0
    for p in prods:
        c_name = clean_name(p.get("recipe_name"))
        q = float(p.get("quantity") or 0)
        if c_name:
            prod_map[c_name] = prod_map.get(c_name, 0.0) + q
            total_produced += q

    # Retseptlar ro'yxati
    r_res = requests.get(f"{SUPABASE_URL}/rest/v1/recipes?select=name", headers=HEADERS, timeout=10)
    recipes = r_res.json() if isinstance(r_res.json(), list) else []

    all_keys = sorted(list(set(list(prod_map.keys()) + list(sold_map.keys()) + [clean_name(r.get("name")) for r in recipes])))

    msg = f"🏭 <b>{b_title}</b>\n"
    msg += f"<i>(01.11.2026 dan boshlab hisoblangan)</i>\n"
    msg += f"🟢 Jami Ishlab Chiqarildi: <b>{total_produced:,.0f} qop</b>\n"
    msg += f"🔴 Jami Sotildi: <b>{total_sold:,.0f} qop</b>\n"
    msg += "═" * 24 + "\n\n"
    msg += "<b>📦 Retseptlar Bo'yicha Real Qoldiq:</b>\n\n"

    real_closing_all = 0
    for k in all_keys:
        if not k:
            continue
        p_qty = prod_map.get(k, 0.0)
        s_qty = sold_map.get(k, 0.0)
        bal = max(0.0, p_qty - s_qty)
        real_closing_all += bal

        status = "🟢" if bal > 50 else ("🟡" if bal > 0 else "🔴")
        display_name = k.upper()
        msg += f"{status} <b>{display_name}</b>:\n"
        msg += f"   Ishlab chiqarildi: +{p_qty:,.0f} qop\n"
        msg += f"   Sotildi: -{s_qty:,.0f} qop\n"
        msg += f"   👉 <b>Haqiqiy Qoldiq: {bal:,.0f} qop</b>\n\n"

    msg += "═" * 24 + "\n"
    msg += f"📦 <b>Ombordagi Umumiy Real Qoldiq: {real_closing_all:,.0f} qop</b>"

    kb = {"inline_keyboard": [[{"text": "🔙 Boshqa korxonani tanlash", "callback_data": "branch_back"}]]}
    return msg, kb

# ----------------- 2. XOMASHYO VA BO'SH QOPLAR -----------------
def get_materials_report():
    url = f"{SUPABASE_URL}/rest/v1/materials?select=*,branches(name,city)&order=name.asc"
    res = requests.get(url, headers=HEADERS, timeout=10)
    materials = res.json() if isinstance(res.json(), list) else []

    if not materials:
        return "📦 Omborda xomashyo topilmadi."

    msg = "📦 <b>Xomashyo & Bo'sh Qoplar Qoldig'i:</b>\n\n"
    for m in materials:
        name = m.get("name") or "Material"
        stock = float(m.get("stock") or 0)
        unit = m.get("unit") or "kg"
        br = m.get("branches", {})
        br_str = f" <i>({br.get('city')})</i>" if br else ""
        icon = "🟡" if "qop" in name.lower() else "🔹"
        msg += f"{icon} <b>{name}</b>{br_str}: <b>{stock:,.0f} {unit}</b>\n"
    return msg

# ----------------- 3. KASSA HISOBOTI -----------------
def get_kassa_report():
    url = f"{SUPABASE_URL}/rest/v1/kassa?select=*&order=date.asc"
    res = requests.get(url, headers=HEADERS, timeout=10)
    all_rows = res.json() if isinstance(res.json(), list) else []

    kirim = sum(float(r.get("amount") or 0) for r in all_rows if str(r.get("type", "")).lower() == "kirim")
    chiqim = sum(float(r.get("amount") or 0) for r in all_rows if str(r.get("type", "")).lower() == "chiqim")
    qoldiq = kirim - chiqim

    today_str = get_uz_today().strftime("%Y-%m-%d")
    today_rows = [r for r in all_rows if str(r.get("date") or "")[:10] == today_str]
    t_k = sum(float(r.get("amount") or 0) for r in today_rows if str(r.get("type", "")).lower() == "kirim")
    t_ch = sum(float(r.get("amount") or 0) for r in today_rows if str(r.get("type", "")).lower() == "chiqim")

    msg = (
        "💰 <b>KASSA & KUNLIK BALANS:</b>\n\n"
        f"🟢 Jami Kirim: <b>+{kirim:,.0f} so'm</b>\n"
        f"🔴 Jami Chiqim: <b>-{chiqim:,.0f} so'm</b>\n"
        f"💵 <b>Hozirgi Kassa Qoldig'i: {qoldiq:,.0f} so'm</b>\n"
        "═" * 24 + "\n"
        f"🗓 <b>Bugungi aylanma ({today_str}):</b>\n"
        f"• Kirim: +{t_k:,.0f} so'm\n"
        f"• Chiqim: -{t_ch:,.0f} so'm\n"
        f"• Sof aylanma: {t_k - t_ch:+,.0f} so'm\n"
    )
    return msg

# ----------------- 4. SOTUV DAFTARI -----------------
def get_sales_report():
    url = f"{SUPABASE_URL}/rest/v1/customer_sales?select=*,customers(name)&is_ostatka=eq.false&order=id.desc&limit=10"
    res = requests.get(url, headers=HEADERS, timeout=10)
    sales = res.json() if isinstance(res.json(), list) else []

    if not sales:
        return "📒 <i>Sotuvlar jurnali bo'sh.</i>"

    msg = "📒 <b>Oxirgi 10 ta Savdo Yozuvi:</b>\n\n"
    for i, s in enumerate(sales, 1):
        c_name = s.get("customers", {}).get("name") if s.get("customers") else "Mijoz"
        p_name = s.get("product_name") or "Mahsulot"
        qty = s.get("quantity") or 0
        total = float(s.get("total") or 0)
        s_date = str(s.get("date") or "")[:10]
        msg += f"<b>{i}. {c_name}</b> ({s_date})\n"
        msg += f"   📦 {p_name}: {qty} ta = <b>{total:,.0f} so'm</b>\n"
    return msg

# ----------------- 5. QARZDOR MIJOZLAR (HUDUDLAR BO'YICHA) -----------------
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

    text = (
        "👥 <b>Qarzdor Mijozlar Bo'limi</b>\n"
        f"💵 Jami Umumiy Qarz: <b>{total_all:,.0f} so'm</b>\n\n"
        "Hududni (papkani) tanlang:"
    )
    return text, {"inline_keyboard": buttons}

def get_clients_keyboard_by_region(region_name: str):
    regions = get_debts_structure()
    clients = regions.get(region_name, {})
    buttons = []
    reg_total = sum(c["debt"] for c in clients.values())

    for c_name in sorted(clients.keys(), key=lambda s: s.lower()):
        d_val = clients[c_name]["debt"]
        buttons.append([{"text": f"👤 {c_name} — {d_val:,.0f}", "callback_data": f"debts_cl_{region_name}_{c_name}"}])

    buttons.append([{"text": "🔙 Boshqa hududni tanlash", "callback_data": "debts_back_regions"}])
    text = (
        f"📁 <b>{region_name.upper()} hududi:</b>\n"
        f"💵 Jami Qarz: <b>{reg_total:,.0f} so'm</b>\n\n"
        "Mijozni tanlang:"
    )
    return text, {"inline_keyboard": buttons}

# ----------------- 6. ISHCHILAR OYLIGI (OYLIK PAPKALAR VA HISOB-KITOB) -----------------
def get_worker_months_keyboard():
    # Mavjud oylar ro'yxati
    months = ["2026-11", "2026-10", "2026-09"]
    cur_m = get_uz_today().strftime("%Y-%m")
    if cur_m not in months:
        months.insert(0, cur_m)

    buttons = []
    for m in months:
        buttons.append([{"text": f"📅 {m} Oyi Maoshlari", "callback_data": f"w_month_{m}"}])

    text = "👨‍🔧 <b>Ishchilar Oyligi & Oylik Hisob-Kitob Arxivlari:</b>\nQaysi oy bo'yicha hisobotni ko'rmoqchisiz?"
    return text, {"inline_keyboard": buttons}

def get_worker_monthly_report(m_str: str):
    # 1. Ishchilar
    w_res = requests.get(f"{SUPABASE_URL}/rest/v1/workers?select=*&order=name.asc", headers=HEADERS, timeout=10)
    workers = w_res.json() if isinstance(w_res.json(), list) else []

    # 2. Oylik hisob-kitob qatorlari (worker_monthly_settlements)
    sett_res = requests.get(f"{SUPABASE_URL}/rest/v1/worker_monthly_settlements?month=eq.{m_str}", headers=HEADERS, timeout=10)
    settlements = sett_res.json() if isinstance(sett_res.json(), list) else []
    sett_map = {s.get("worker_id"): s for s in settlements}

    # 3. Shu oyda berilgan avanslar (worker_salaries)
    sal_res = requests.get(f"{SUPABASE_URL}/rest/v1/worker_salaries?select=*&date=gte.{m_str}-01&date=lte.{m_str}-31", headers=HEADERS, timeout=10)
    salaries = sal_res.json() if isinstance(sal_res.json(), list) else []

    # 4. Korxonada shu oyda ishlab chiqarilgan qoplar jami
    p_res = requests.get(f"{SUPABASE_URL}/rest/v1/production?select=quantity&date=gte.{m_str}-01&date=lte.{m_str}-31", headers=HEADERS, timeout=10)
    prods = p_res.json() if isinstance(p_res.json(), list) else []
    factory_total_bags = sum(float(p.get("quantity") or 0) for p in prods)

    if not workers:
        return "Tizimda ishchilar topilmadi.", None

    tot_earned = 0
    tot_advances = 0
    tot_claimed_bags = 0

    msg = f"👨‍🔧 <b>{m_str} OYI ISHCHILAR MAOSHI HISOBOTI:</b>\n"
    msg += f"🏭 Korxonada ishlab chiqarildi: <b>{factory_total_bags:,.0f} qop</b>\n"
    msg += "═" * 24 + "\n\n"

    for i, w in enumerate(workers, 1):
        w_id = w.get("id")
        w_name = w.get("name") or "Ishchi"
        w_role = w.get("role") or "Xodim"
        is_piece = (w.get("salary_type") or "piecework") == "piecework"

        sett = sett_map.get(w_id, {})
        p_qty = float(sett.get("produced_qty") or 0)
        rate = float(sett.get("rate") or w.get("rate") or 0)

        total_salary = (p_qty * rate) if is_piece else rate
        advances = sum(float(s.get("amount") or 0) for s in salaries if s.get("worker_id") == w_id)
        rem_debt = total_salary - advances

        tot_claimed_bags += p_qty
        tot_earned += total_salary
        tot_advances += advances

        type_str = "Dona (Ishbay)" if is_piece else "Oylik"
        msg += f"<b>{i}. {w_name}</b> ({w_role} - {type_str})\n"
        if is_piece:
            msg += f"   📦 Ishlagan qoplari: <b>{p_qty:,.0f} dona</b> ({rate:,.0f} so'm/dona)\n"
        msg += f"   💵 Jami maoshi: <b>{total_salary:,.0f} so'm</b>\n"
        msg += f"   💳 Olingan avanslar: <b>-{advances:,.0f} so'm</b>\n"
        msg += f"   👉 <b>Qoldiq haq: {rem_debt:,.0f} so'm</b>\n"
        msg += "────────────────────\n"

    msg += f"\n📊 <b>{m_str} Oyi Jamlanmasi:</b>\n"
    msg += f"• Ishchilarga hisoblandi: <b>{tot_earned:,.0f} so'm</b>\n"
    msg += f"• To'langan avanslar: <b>{tot_advances:,.0f} so'm</b>\n"
    msg += f"• Qolgan qarz: <b>{tot_earned - tot_advances:,.0f} so'm</b>\n"

    kb = {"inline_keyboard": [[{"text": "🔙 Boshqa oyni tanlash", "callback_data": "w_month_back"}]]}
    return msg, kb

# ----------------- 7. BONUSLAR -----------------
def get_bonus_report():
    url = f"{SUPABASE_URL}/rest/v1/production?select=quantity,total_bonus,has_bonus&has_bonus=eq.true"
    res = requests.get(url, headers=HEADERS, timeout=10)
    bonuses = res.json() if isinstance(res.json(), list) else []

    total_qop = sum(float(b.get("quantity") or 0) for b in bonuses)
    total_sum = sum(float(b.get("total_bonus") or 0) for b in bonuses)

    msg = (
        "🎁 <b>Bonuslar Umumiy Tahlili:</b>\n\n"
        f"🏷 Jami Bonusli Qoplar: <b>{total_qop:,.0f} dona</b>\n"
        f"💸 Sarflangan Bonus Mablag'i: <b>{total_sum:,.0f} so'm</b>\n"
    )
    return msg

# ----------------- CALLBACK TUGMALARNI QAYTA ISHLASH -----------------
def handle_callback_query(callback_id: str, chat_id: int, message_id: int, data: str):
    try:
        requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": callback_id}, timeout=5)
    except:
        pass

    # Korxona ostatkasi
    if data == "branch_back":
        text, kb = get_enterprises_report()
        edit_message_text(chat_id, message_id, text, reply_markup=kb)
        return

    if data.startswith("branch_ost_"):
        b_id = data.replace("branch_ost_", "")
        text, kb = get_production_breakdown(b_id)
        edit_message_text(chat_id, message_id, text, reply_markup=kb)
        return

    # Ishchilar oyligi oylik papkasi
    if data == "w_month_back":
        text, kb = get_worker_months_keyboard()
        edit_message_text(chat_id, message_id, text, reply_markup=kb)
        return

    if data.startswith("w_month_"):
        m_str = data.replace("w_month_", "")
        text, kb = get_worker_monthly_report(m_str)
        edit_message_text(chat_id, message_id, text, reply_markup=kb)
        return

    # Qarzdorlar bo'limi
    if data == "debts_back_regions":
        text, kb = get_region_keyboard()
        edit_message_text(chat_id, message_id, text, reply_markup=kb)
        return

    if data.startswith("debts_reg_"):
        region_name = data.replace("debts_reg_", "")
        text, kb = get_clients_keyboard_by_region(region_name)
        edit_message_text(chat_id, message_id, text, reply_markup=kb)
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
            f"💰 Hozirgi qarzdorlik: <b>{cl_info.get('debt', 0):,.0f} so'm</b>\n"
        )
        kb = {"inline_keyboard": [[{"text": f"🔙 {reg} ro'yxatiga qaytish", "callback_data": f"debts_reg_{reg}"}]]}
        edit_message_text(chat_id, message_id, msg, reply_markup=kb)
        return

# ----------------- ASOSIY XABARLARNI QAYTA ISHLASH -----------------
def handle_text(chat_id: int, user_id: int, text: str, first_name: str):
    if not is_admin(user_id):
        send_message(chat_id, f"Assalomu alaykum! Siz Memor ERP tizimida ro'yxatdan o'tmagansiz (Telegram ID: {user_id}).")
        return

    clean_text = text.strip()

    if clean_text in ["/start", "start"]:
        send_message(
            chat_id,
            f"Assalomu alaykum, <b>{first_name}</b>!\n"
            "Memor ERP boshqaruv tizimi faol. Kerakli bo'limni tanlang:",
            reply_markup=MAIN_KEYBOARD,
        )

    elif clean_text == "🏭 Korxonalar & Ostatka":
        msg, kb = get_enterprises_report()
        send_message(chat_id, msg, reply_markup=kb)

    elif clean_text == "📦 Xomashyo & Qoplar":
        send_message(chat_id, get_materials_report())

    elif clean_text == "💰 Kassa Balansi":
        send_message(chat_id, get_kassa_report())

    elif clean_text == "📒 Sotuv Daftari":
        send_message(chat_id, get_sales_report())

    elif clean_text == "👥 Qarzdor Mijozlar":
        text_reg, kb_reg = get_region_keyboard()
        send_message(chat_id, text_reg, reply_markup=kb_reg)

    elif clean_text == "👨‍🔧 Ishchilar Oyligi (Arxiv)":
        text_m, kb_m = get_worker_months_keyboard()
        send_message(chat_id, text_m, reply_markup=kb_m)

    elif clean_text == "🎁 Bonuslar Tahlili":
        send_message(chat_id, get_bonus_report())

    # Mijoz qidiruvi
    else:
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
                    msg += f"👤 <b>{name}</b> (📍 {reg}){phone}\n💰 Qarz: <b>{info['debt']:,.0f} so'm</b>\n────────────────\n"
                send_message(chat_id, msg)
            else:
                send_message(chat_id, f"🔍 '{clean_text}' bo'yicha ma'lumot topilmadi.\nBo'limni tanlang:", reply_markup=MAIN_KEYBOARD)
        except Exception as e:
            send_message(chat_id, f"Xatolik: {e}")

def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN topilmadi!")
        return

    threading.Thread(target=start_dummy_server, daemon=True).start()
    logging.info(f"Render porti ({PORT}) ochiq saqlanmoqda...")
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

