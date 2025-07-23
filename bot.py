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

def label_for(data: str) -> str:
    return {
        'terms': "Terms & Policies",
        'email': "Email",
        'currency': "Валюта",
        '404': "404 Errors",
        'cookie': "Cookie Consent",
        'lang': "Язык сайта",
        'all': "Полная проверка",
    }.get(data, data)


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
        [InlineKeyboardButton("📱 Телефон", callback_data='phone')],
        [InlineKeyboardButton("💶 Используемая валюта", callback_data='currency')],
        [InlineKeyboardButton("🔗 404 Errors", callback_data='404')],
        [InlineKeyboardButton("🍪 Cookie Consent", callback_data='cookie')],
        [InlineKeyboardButton("🌐 Язык сайта", callback_data='lang')],
        [InlineKeyboardButton("🔍 Проверить всё", callback_data='all')],
        [InlineKeyboardButton("🔄 Новый сайт", callback_data='new_site')],
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

    # ⚠️ Показываем, что проверка запущена
    try:
        await query.edit_message_text(f"⏳ Выполняю проверку «{label_for(query.data)}» для: {url}")
    except Exception:
        pass  # Иногда Telegram не даёт изменить сообщение — игнорируем

    result_text = await run_checker(query.data, url)

    # ✅ Отправляем результат
    await query.message.reply_text(result_text)

    # 🔁 Возвращаем кнопки
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
                location = "на главной" if result['source'] == "main" else "в Privacy Policy"
                return f"📧 Найденные почты ({location}):\n{emails}"
            else:
                return "📧 Email не найден ни на главной, ни в Privacy Policy."


        elif mode == 'currency':
            result = await checker.check_currency()
            if not result["found"] or not result["symbols"]:
                return "💱 Валюта не найдена на сайте."
            symbols = ", ".join([f"{sym} ({cnt})" for sym, cnt in result["symbols"].items()])
            most_common_symbol = result.get("most_common_symbol", "не определён")
            return (
                f"💱 Найдены валютные символы/коды:\n{symbols}\n\n"
                f"🏆 Самый часто используемый: {most_common_symbol}"
            )

        elif mode == 'cookie':
            consent = checker.check_cookie_consent()
            return f"🍪 Cookie Consent Banner: {'✅ Найден' if consent else '❌ Не найден'}"

        elif mode == 'phone':
            result = checker.check_contact_phone()
            if result['found']:
                phones = "\n".join(result['phones'])
                location = "на главной" if result['source'] == "main" else "в Privacy Policy"
                return f"📱 Найденные телефоны ({location}):\n{phones}"
            else:
                return "📱 Телефон не найден ни на главной, ни в Privacy Policy."

        elif mode == '404':
            broken = await checker.check_404_errors()
            if broken:
                lines = "\n".join([f"{link} ({code})" for link, code in broken])
                return f"🚫 Найдены битые ссылки:\n{lines}"
            else:
                return "✅ Все ссылки работают!"
        elif mode == 'lang':
            res = checker.check_language_consistency()
            if res["language"] == "error":
                result_text = "🌐 Ошибка при определении языка."
            elif res["language"] == "unknown":
                result_text = "🌐 Не удалось определить язык сайта."
            else:
                lang = res['language'].upper()
                status = "✅ Однородно" if res["consistent"] else "⚠️ Найдены разные языки"
                result_text = f"🌐 Язык сайта: {lang}\n{status}"
            return result_text
        elif mode == 'all':
            t = checker.check_terms_and_policies()
            e = checker.check_contact_email()
            c = await checker.check_currency()  # Асинхронный вызов
            b = await checker.check_404_errors()
            cookie = checker.check_cookie_consent()
            l = checker.check_language_consistency()
            p = checker.check_contact_phone()
            # Обработка языка
            lang_part = ""
            if l["language"] == "error":
                lang_part = "🌐 Язык: ошибка при определении"
            elif l["language"] == "unknown":
                lang_part = "🌐 Язык: не удалось определить"
            else:
                lang_code = l["language"].upper()
                status = "✅ Однородно" if l["consistent"] else "⚠️ Найдены разные языки"
                lang_part = f"🌐 Язык сайта: {lang_code}\n{status}"
            # Обработка валют
            if c["found"] and c["symbols"]:
                currency_part = (
                    f"💱 Валюта:\n"
                    f"{', '.join([f'{sym} ({cnt})' for sym, cnt in c['symbols'].items()])}\n"
                    f"🏆 Самый часто используемый: {c.get('most_common_symbol', 'не определён')}"
                )
            else:
                currency_part = "💱 Валюта: ❌ Не найдена"
            # Финальный сбор всех результатов
            parts = [
                "🔍 Terms & Policies:\n" + "\n".join([f"{k}: {'✅' if v else '❌'}" for k, v in t.items()]),
                f"📧 Email: {'✅ ' + ', '.join(e['emails']) if e['found'] else '❌ Not found'}",
                currency_part,
                f"🍪 Cookie Consent Banner: {'✅ Найден' if cookie else '❌ Не найден'}",
                f"🚫 Битые ссылки:\n" + "\n".join(
                    [f"{link} ({code})" for link, code in b]) if b else "✅ Все ссылки работают!",
                f"📱 Телефоны: {'✅ ' + ', '.join(p['phones']) if p['found'] else '❌ Не найдены'}",
                lang_part
            ]
            return "\n\n".join(parts)
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
