import os
import logging
import requests
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ADMIN_IDS = os.getenv("TELEGRAM_ADMIN_USER_IDS", "")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

MAIN_KEYBOARD = [
    ["📦 Ombor Qoldig'i", "💰 Kassa Qoldig'i"],
    ["👥 Mijozlar Qarzi", "📊 Kunlik Sotuvlar"],
]

def is_admin(user_id: int) -> bool:
    admin_list = [i.strip() for i in ADMIN_IDS.split(",") if i.strip()]
    return str(user_id) in admin_list

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    reply_markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    
    if not is_admin(user_id):
        await update.message.reply_text(
            f"Salom! Siz tizimda ro'yxatdan o'tmagansiz (Sizning Telegram ID: {user_id})."
        )
        return

    await update.message.reply_text(
        f"Assalomu alaykum, {update.effective_user.first_name}!\n"
        "Memor ERP boshqaruv botiga xush kelibsiz.",
        reply_markup=reply_markup,
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if not is_admin(user_id):
        await update.message.reply_text("Sizga bu ma'lumotlarni ko'rish uchun ruxsat yo'q.")
        return

    # 1. Ombor Qoldig'i
    if text == "📦 Ombor Qoldig'i":
        try:
            url = f"{SUPABASE_URL}/rest/v1/materials?select=name,stock,unit"
            res = requests.get(url, headers=HEADERS, timeout=10)
            materials = res.json()
            
            if not materials or not isinstance(materials, list):
                await update.message.reply_text("Omborda mahsulotlar topilmadi.")
                return

            msg = "📦 <b>Ombordagi mavjud qoldiqlar:</b>\n\n"
            for m in materials:
                msg += f"• <b>{m.get('name')}</b>: {m.get('stock')} {m.get('unit', '')}\n"
            await update.message.reply_html(msg)
        except Exception as e:
            await update.message.reply_text(f"Xatolik: {e}")

    # 2. Kassa Qoldig'i
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
            await update.message.reply_html(msg)
        except Exception as e:
            await update.message.reply_text(f"Xatolik: {e}")

    # 3. Mijozlar Qarzi
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

            active_debts = {k: v for k, v in debts.items() if v > 0}
            if not active_debts:
                await update.message.reply_text("Qarzdor mijozlar yo'q.")
                return

            msg = "👥 <b>Qarzdor mijozlar:</b>\n\n"
            for name, debt in sorted(active_debts.items(), key=lambda x: x[1], reverse=True):
                msg += f"• <b>{name}</b>: {debt:,.0f} so'm\n"
            await update.message.reply_html(msg)
        except Exception as e:
            await update.message.reply_text(f"Xatolik: {e}")

    # 4. Kunlik Sotuvlar
    elif text == "📊 Kunlik Sotuvlar":
        try:
            url = f"{SUPABASE_URL}/rest/v1/customer_sales?select=product_name,quantity,total,date&order=id.desc&limit=10"
            res = requests.get(url, headers=HEADERS, timeout=10)
            sales = res.json()

            if not sales or not isinstance(sales, list):
                await update.message.reply_text("Sotuvlar topilmadi.")
                return

            msg = "📊 <b>Oxirgi 10 ta savdo amaliyoti:</b>\n\n"
            for s in sales:
                msg += f"• [{s.get('date')}] <b>{s.get('product_name')}</b> - {s.get('quantity')} ta ({float(s.get('total') or 0):,.0f} so'm)\n"
            await update.message.reply_html(msg)
        except Exception as e:
            await update.message.reply_text(f"Xatolik: {e}")

def main():
    if not BOT_TOKEN:
        print("XATO: BOT_TOKEN aniqlanmadi!")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot muvaffaqiyatli ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()
