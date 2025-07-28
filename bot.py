import logging
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from checker import WebsiteChecker

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_FILE = Path("user_sites.json")

# === Работа с файлами ===
def load_user_sites():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_user_sites(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# === Главное меню ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔎 Проверить сайт", callback_data="check_site")],
        [InlineKeyboardButton("📋 Проверить сайты из списка", callback_data="check_all_sites")],
        [InlineKeyboardButton("⚙️ Автопроверка", callback_data="autocheck_menu")]
    ]
    await update.message.reply_text("Привет! 👋 Выберите опцию:", reply_markup=InlineKeyboardMarkup(keyboard))

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🔎 Проверить сайт", callback_data="check_site")],
        [InlineKeyboardButton("📋 Проверить сайты из списка", callback_data="check_all_sites")],
        [InlineKeyboardButton("⚙️ Автопроверка", callback_data="autocheck_menu")]
    ]
    await query.edit_message_text("🔙 Главное меню", reply_markup=InlineKeyboardMarkup(keyboard))

# === Меню автопроверки ===
async def autocheck_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("➕ Добавить сайт", callback_data="add_site")],
        [InlineKeyboardButton("❌ Удалить сайт", callback_data="remove_site")],
        [InlineKeyboardButton("📋 Список сайтов", callback_data="list_sites")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]
    ]
    await query.edit_message_text("⚙️ Меню автопроверки", reply_markup=InlineKeyboardMarkup(keyboard))

# === Добавление сайта ===
async def add_site_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["adding_site"] = True
    await query.message.reply_text("Введите ссылку сайта для автопроверки:")

# === Удаление сайта ===
async def remove_site_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    data = load_user_sites()
    sites = data.get(user_id, [])

    if not sites:
        return await query.message.reply_text("📭 У вас нет сайтов для удаления.")

    keyboard = [[InlineKeyboardButton(f"❌ {s}", callback_data=f"remove_{s}")] for s in sites]
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="autocheck_menu")])
    await query.message.reply_text("Выберите сайт для удаления:", reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_site_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    site = query.data.replace("remove_", "")
    data = load_user_sites()
    sites = data.get(user_id, [])

    if site in sites:
        sites.remove(site)
        data[user_id] = sites
        save_user_sites(data)
        await query.edit_message_text(f"🗑️ Сайт удалён: {site}")
    else:
        await query.answer("Сайт не найден.")

# === Список сайтов ===
async def list_sites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    sites = load_user_sites().get(user_id, [])
    msg = "📋 Ваши сайты:\n" + "\n".join([f"🔗 {s}" for s in sites]) if sites else "📭 Список пуст."
    await query.message.reply_text(msg)

# === Проверка сайта ===
async def check_site_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["checking_site"] = True
    await query.message.reply_text("Введите ссылку сайта для проверки:")

# === Обработка текста ===
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    user_id = str(update.effective_user.id)

    if user_data.get("adding_site"):
        url = update.message.text.strip()
        data = load_user_sites()
        sites = data.get(user_id, [])
        if url not in sites:
            sites.append(url)
            data[user_id] = sites
            save_user_sites(data)
            await update.message.reply_text(f"✅ Сайт добавлен: {url}")
        else:
            await update.message.reply_text("⚠️ Этот сайт уже есть в списке.")
        user_data["adding_site"] = False
        return

    if user_data.get("checking_site"):
        url = update.message.text.strip()
        user_data["checking_site"] = False
        await site_menu(update.message, url)
        return

    await update.message.reply_text("⚠️ Используйте меню для выбора действия.")

# === Меню проверок сайта ===
async def site_menu(message_or_query, url):
    keyboard = [
        [InlineKeyboardButton("✅ Terms & Policies", callback_data=f"terms_{url}")],
        [InlineKeyboardButton("📧 Email", callback_data=f"email_{url}")],
        [InlineKeyboardButton("📱 Телефон", callback_data=f"phone_{url}")],
        [InlineKeyboardButton("💱 Валюта", callback_data=f"currency_{url}")],
        [InlineKeyboardButton("🍪 Cookie", callback_data=f"cookie_{url}")],
        [InlineKeyboardButton("🌐 Язык сайта", callback_data=f"lang_{url}")],
        [InlineKeyboardButton("🔗 404 Errors", callback_data=f"errors_{url}")],
        [InlineKeyboardButton("🔍 Проверить всё", callback_data=f"all_{url}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]
    ]
    await message_or_query.reply_text(f"🔗 Сайт: {url}", reply_markup=InlineKeyboardMarkup(keyboard))

# === Обработка кнопок проверок ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    modes = {
        "terms_": "terms", "email_": "email", "phone_": "phone",
        "currency_": "currency", "cookie_": "cookie", "lang_": "lang",
        "errors_": "404", "all_": "all"
    }
    mode = next((m for k, m in modes.items() if data.startswith(k)), None)
    if not mode:
        return

    url = data.split("_", 1)[1].strip()
    parsed = urlparse(url)

    # ✅ Проверяем корректность URL
    if not parsed.scheme or not parsed.netloc:
        await query.message.reply_text("❌ Ошибка: Некорректный URL")
        logger.error(f"Некорректный URL в callback: {url}")
        return

    await query.message.reply_text("🔄 Проверка запущена...")

    try:
        result = await run_checker(mode, url)
        await query.message.reply_text(result[:4000])
    except Exception as e:
        logger.exception("Ошибка при проверке")
        await query.message.reply_text(f"❌ Ошибка при проверке сайта: {e}")

# === Проверка всех сайтов ===
async def check_all_sites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    sites = load_user_sites().get(user_id, [])

    if not sites:
        return await query.message.reply_text("📭 У вас нет сайтов.")

    await query.message.reply_text("🔄 Проверяю все сайты...")
    report = []
    for url in sites:
        try:
            result = await run_checker("all", url)
            report.append(f"✅ {url}:\n{result[:1000]}")
        except Exception as e:
            report.append(f"❌ {url}: {e}")

    await query.message.reply_text("\n\n".join(report)[:4000])

# === Автопроверка ===
async def run_daily_checks(app):
    bot = app.bot
    data = load_user_sites()
    for user_id, sites in data.items():
        report = []
        for url in sites:
            try:
                result = await run_checker("all", url)
                report.append(f"✅ {url}:\n{result[:1000]}")
            except Exception as e:
                report.append(f"❌ {url}: {e}")
        if report:
            await bot.send_message(chat_id=user_id, text="\n\n".join(report)[:4000])

async def on_startup(app):
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(run_daily_checks, "interval", hours=24, args=[app])
    scheduler.start()

# === Логика проверок ===
async def run_checker(mode: str, url: str) -> str:
    checker = WebsiteChecker(url)
    try:
        if mode == "terms":
            t = checker.check_terms_and_policies()
            return "🔍 Terms:\n" + "\n".join([f"{k}: {'✅' if v else '❌'}" for k, v in t.items()])
        elif mode == "email":
            e = checker.check_contact_email()
            return f"📧 Email: {'✅ ' + ', '.join(e['emails']) if e['found'] else '❌'}"
        elif mode == "phone":
            p = checker.check_contact_phone()
            return f"📱 Телефоны: {'✅ ' + ', '.join(p['phones']) if p['found'] else '❌'}"
        elif mode == "currency":
            c = await checker.check_currency()
            if not c["found"]:
                return "💱 Валюта не найдена"
            symbols = ", ".join([f"{sym} ({cnt})" for sym, cnt in c['symbols'].items()])
            return f"💱 Валюты:\n{symbols}\n🏆 Чаще всего: {c['most_common_symbol']}"
        elif mode == "cookie":
            cookie = checker.check_cookie_consent()
            return f"🍪 Cookie: {'✅ Найден' if cookie else '❌'}"
        elif mode == "lang":
            l = checker.check_language_consistency()
            return f"🌐 Язык: {l['language'].upper()}, {'✅ Однородно' if l['consistent'] else '⚠️ Разные языки'}"
        elif mode == "404":
            b = await checker.check_404_errors()
            return f"🚫 Битые ссылки:\n" + "\n".join([f"{link} ({code})" for link, code in b]) if b else "✅ Все ссылки работают!"
        elif mode == "all":
            t = checker.check_terms_and_policies()
            e = checker.check_contact_email()
            c = await checker.check_currency()
            b = await checker.check_404_errors()
            cookie = checker.check_cookie_consent()
            l = checker.check_language_consistency()
            p = checker.check_contact_phone()
            return "\n\n".join([
                "🔍 Terms:\n" + "\n".join([f"{k}: {'✅' if v else '❌'}" for k, v in t.items()]),
                f"📧 Email: {'✅ ' + ', '.join(e['emails']) if e['found'] else '❌'}",
                f"💱 Валюта: " + (", ".join([f"{sym} ({cnt})" for sym, cnt in c['symbols'].items()]) if c['found'] else "❌"),
                f"🍪 Cookie: {'✅ Найден' if cookie else '❌'}",
                f"🚫 Битые ссылки:\n" + "\n".join([f"{link} ({code})" for link, code in b]) if b else "✅ Все ссылки работают",
                f"📱 Возможные телефоны: {'✅ ' + ', '.join(p['phones']) if p['found'] else '❌'}",
                f"🌐 Язык: {l['language'].upper()}, {'✅ Однородно' if l['consistent'] else '⚠️'}"
            ])
        return "Неизвестная команда"
    finally:
        checker.close()

# === MAIN ===
def main():
    app = ApplicationBuilder().token("7615217437:AAEpv1d7xQ2CT-IpUBvV70TRxfdHTRikEvE").post_init(on_startup).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(autocheck_menu, pattern="^autocheck_menu$"))
    app.add_handler(CallbackQueryHandler(add_site_start, pattern="^add_site$"))
    app.add_handler(CallbackQueryHandler(remove_site_start, pattern="^remove_site$"))
    app.add_handler(CallbackQueryHandler(remove_site_callback, pattern=r"^remove_"))
    app.add_handler(CallbackQueryHandler(list_sites, pattern="^list_sites$"))
    app.add_handler(CallbackQueryHandler(check_site_start, pattern="^check_site$"))
    app.add_handler(CallbackQueryHandler(check_all_sites, pattern="^check_all_sites$"))
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(terms|email|phone|currency|cookie|lang|errors|all)_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()
