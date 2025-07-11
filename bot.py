import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from checker import WebsiteChecker

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

user_state = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_state.pop(user_id, None)
    await update.message.reply_text(
        "Привет! 👋 Пришли ссылку на сайт для проверки."
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text.strip()
    user_state[user_id] = {'url': url}
    await send_options(update.message, url)

async def send_options(message_or_query, url, force_new=False):
    keyboard = [
        [InlineKeyboardButton("✅ Terms & Policies", callback_data='terms')],
        [InlineKeyboardButton("📧 Email", callback_data='email')],
        [InlineKeyboardButton("💶 Валюта", callback_data='currency')],
        [InlineKeyboardButton("🔗 404 Errors", callback_data='404')],
        [InlineKeyboardButton("🔍 Проверить всё", callback_data='all')],
        [InlineKeyboardButton("🔄 Новый сайт", callback_data='new_site')]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    text = f"🔗 Сайт: {url}\nВыбери, что проверить:"

    if isinstance(message_or_query, CallbackQuery):
        if force_new:
            await message_or_query.message.reply_text(text, reply_markup=markup)
        else:
            await message_or_query.edit_message_text(text, reply_markup=markup)
    elif isinstance(message_or_query, Message):
        await message_or_query.reply_text(text, reply_markup=markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    user_data = user_state.get(user_id)

    if query.data == 'new_site':
        user_state.pop(user_id, None)
        await query.edit_message_text("Ок! 🆕 Пришли новую ссылку.")
        return

    if not user_data:
        await query.edit_message_text("Начни с /start и пришли ссылку.")
        return

    url = user_data['url']

    result_text = await run_checker(query.data, url)

    await query.message.reply_text(result_text)
    await send_options(query, url, force_new=True)

async def run_checker(mode: str, url: str) -> str:
    checker = WebsiteChecker(url)

    try:
        if mode == 'terms':
            result = checker.check_terms_and_policies()
            details = "\n".join([f"{k}: {'✅' if v else '❌'}" for k, v in result.items()])
            return f"🔍 Terms & Policies:\n{details}"

        elif mode == 'email':
            result = checker.check_contact_email()
            if result['found']:
                emails = "\n".join(result['emails'])
                return f"📧 Найденные почты:\n{emails}"
            else:
                return "📧 Email не найден 😞"

        elif mode == 'currency':
            ok = checker.check_currency()
            return f"💶 Валюта указана правильно: {'✅' if ok else '❌'}"

        elif mode == '404':
            broken = await checker.check_404_errors()
            if broken:
                lines = "\n".join([f"{link} ({code})" for link, code in broken])
                return f"🚫 Найдены битые ссылки:\n{lines}"
            else:
                return "✅ Все ссылки работают!"

        elif mode == 'all':
            t = checker.check_terms_and_policies()
            e = checker.check_contact_email()
            c = checker.check_currency()
            b = await checker.check_404_errors()

            parts = [
                "🔍 Terms & Policies:\n" + "\n".join([f"{k}: {'✅' if v else '❌'}" for k, v in t.items()]),
                f"📧 Email: {'✅ ' + ', '.join(e['emails']) if e['found'] else '❌ Not found'}",
                f"💶 Валюта: {'✅' if c else '❌'}",
                f"🚫 Битые ссылки: \n" + "\n".join([f"{link} ({code})" for link, code in b]) if b else "✅ Все ссылки работают!"
            ]
            return "\n\n".join(parts)

        return "Неизвестная команда."
    finally:
        checker.close()

def main():
    app = ApplicationBuilder().token("7615217437:AAEpv1d7xQ2CT-IpUBvV70TRxfdHTRikEvE").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
