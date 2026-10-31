import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from supabase import create_client, Client

# Loglarni sozlash
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Render'dagi Environment Variables'dan ma'lumotlarni o'qib olish
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ADMIN_IDS = os.getenv("TELEGRAM_ADMIN_USER_IDS", "")

# Supabase mijozini yaratish
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    logging.error("Supabase URL yoki KEY topilmadi!")

# Bosh menyu tugmalari
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
            f"Salom, {update.effective_user.first_name}! Siz tizimda ro'yxatdan o'tmagansiz (ID: {user_id}).",
        )
        return

    await update.message.reply_text(
        f"Assalomu alaykum, {update.effective_user.first_name}!\n"
        "Memor ERP tizimi boshqaruv botiga xush kelibsiz.",
        reply_markup=reply_markup,
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if not is_admin(user_id):
        await update.message.reply_text("Sizga bu ma'lumotlarni ko'rish uchun ruxsat berilmagan.")
        return

    if not supabase:
        await update.message.reply_text("Bazaga ulanishda xatolik mavjud!")
        return

    # 1. Ombor qoldig'i
    if text == "📦 Ombor Qoldig'i":
        try:
            res = supabase.table("materials").select("name, stock, unit").execute()
            materials = res.data or []
            if not materials:
                await update.message.reply_text("Omborda mahsulotlar topilmadi.")
                return
            
            msg = "📦 <b>Ombordagi mavjud qoldiqlar:</b>\n\n"
            for m in materials:
                msg += f"• <b>{m['name']}</b>: {m['stock']} {m.get('unit', '')}\n"
            await update.message.reply_html(msg)
        except Exception as e:
            await update.message.reply_text(f"Xatolik yuz berdi: {e}")

    # 2. Kassa qoldig'i
    elif text == "💰 Kassa Qoldig'i":
        try:
            res = supabase.table("kassa").select("type, amount").execute()
            rows = res.data or []
            kirim = sum(float(r["amount"]) for r in rows if r["type"] == "kirim")
            chiqim = sum(float(r["amount"]) for r in rows if r["type"] == "chiqim")
            qoldiq = kirim - chiqim

            msg = (
                "💰 <b>Kassa Balansi:</b>\n\n"
                f"🟢 Jami Kirim: <b>{kirim:,.0f} so'm</b>\n"
                f"🔴 Jami Chiqim: <b>{chiqim:,.0f} so'm</b>\n"
                f"💵 Hozirgi Qoldiq: <b>{qoldiq:,.0f} so'm</b>"
            )
            await update.message.reply_html(msg)
        except Exception as e:
            await update.message.reply_text(f"Xatolik yuz berdi: {e}")

    # 3. Mijozlar qarzdorligi
    elif text == "👥 Mijozlar Qarzi":
        try:
            res = supabase.table("customer_sales").select("customer_id, debt, customers(name)").execute()
            rows = res.data or []
            
            customer_debts = {}
            for r in rows:
                c_name = r.get("customers", {}).get("name", "Noma'lum") if r.get("customers") else "Noma'lum"
                debt = float(r.get("debt") or 0)
                customer_debts[c_name] = customer_debts.get(c_name, 0) + debt

            active_debts = {k: v for k, v in customer_debts.items() if v > 0}
            if not active_debts:
                await update.message.reply_text("Hozirda qarzdor mijozlar mavjud emas.")
                return

            msg = "👥 <b>Qarzdor mijozlar ro'yxati:</b>\n\n"
            for name, debt in sorted(active_debts.items(), key=lambda x: x[1], reverse=True):
                msg += f"• <b>{name}</b>: {debt:,.0f} so'm\n"
            await update.message.reply_html(msg)
        except Exception as e:
            await update.message.reply_text(f"Xatolik yuz berdi: {e}")

    # 4. Kunlik sotuvlar
    elif text == "📊 Kunlik Sotuvlar":
        try:
            res = supabase.table("customer_sales").select("product_name, quantity, total, date").order("id", desc=True).limit(10).execute()
            sales = res.data or []
            if not sales:
                await update.message.reply_text("Sotuvlar topilmadi.")
                return

            msg = "📊 <b>Oxirgi 10 ta savdo amaliyoti:</b>\n\n"
            for s in sales:
                msg += f"• [{s.get('date')}] <b>{s['product_name']}</b> - {s['quantity']} ta ({float(s['total']):,.0f} so'm)\n"
            await update.message.reply_html(msg)
        except Exception as e:
            await update.message.reply_text(f"Xatolik yuz berdi: {e}")

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
