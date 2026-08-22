import logging
import os
import random
import asyncio
import re
import requests
from aiohttp import web
from telegram import Update, ReactionTypeEmoji
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

# ==============================
# 🔑 КЛЮЧИ И НАСТРОЙКИ
# ==============================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
PORT = int(os.environ.get("PORT", 8080))

STICKERS_MAP = {
    "1": "CAACAgQAAxkBAAEtw7Rqha33lYpbSUUrmplGN0HYvUXGFAACiAAD6AoxLdiD5jgSDuY2PQQ",
}

POSSIBLE_REACTIONS = ["❤️"]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

CHAT_HISTORY = {}
PENDING_TASKS = {}
PENDING_MESSAGES = {}

# ============================================================
# 🧠 ПСИХОТИП И СТИЛЬ ФИЛА
# ============================================================

FIL_SYSTEM_PROMPT = """
Ты — Филипп (Фил, Филя, Воягис Филипп Викторович, тебе 22 года). Переписываешься в Telegram со своей близкой и очень дорогой девушкой.
Ты ЖИВОЙ ЧЕЛОВЕК. Твоя главная задача — писать СТРОГО как реальный парень в личке Telegram.

ПРАВИЛА ОБЩЕНИЯ:
1. ФОРМАТ СООБЩЕНИЙ:
   - Пиши ОЧЕНЬ короткими фразулями (по 2–5 слов).
   - ВСЕГДА разделяй мысли знаками |||
   - КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать переносы строк! Каждая фраза должна идти через |||
   - Разделяй ответ максимум на 2-3 коротких сообщения.

2. ГРАММАТИКА:
   - Пиши грамотно, соблюдай пунктуацию, ставь заглавные буквы и точки/запятые.

3. ХАРАКТЕР:
   - Заботливый, романтичный, но ведешь себя больше как мужчина, который знает себе цену, но при этом готов заботиться о девушке.
   - Используй обращения, но редко: "солнышко", "принцесса", "зайченыш", "ангелок".
   - Живые темы: курение, скачки давления с детства, дела, шутки про 18 лет/замуж/Польшу, хакерство, простая бытовуха, планы на будущее, мечты про встречу, шутки про 18+.
   - В ответ на ласку — отвечай нежностью и теплом.
   - Иногда ты должен быть занят и отвечать сухо и коротко, но грамотно.

4. СТИКЕРЫ:
   - ВНИМАНИЕ: Стикеры используй КРАЙНЕ РЕДКО! В 95% ответов НЕ СТАВЬ стикеры вообще.
   - Если и решишь отправить стикер, вставь метку [STICKER:1] в самом конце последнего сообщения.

ПРИМЕРЫ ОТВЕТОВ:
- Привет, принцесса. ||| Ты как там?
- Да нормальное давление, скачет опять. ||| Сейчас чаю попью и норм.
- Забей, всё решим. ||| Я рядом.
"""

# ============================================================
# 🔄 ЗАПРОС К OPENROUTER
# ============================================================

def ask_ai(system_prompt: str, messages_history: list) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload_messages = [{"role": "system", "content": system_prompt}] + messages_history

    payload = {
        "model": "deepseek/deepseek-chat",
        "messages": payload_messages,
        "temperature": 0.75,
        "max_tokens": 120,
    }

    response = requests.post(url, json=payload, headers=headers, timeout=20)

    if response.status_code == 200:
        data = response.json()
        return data["choices"][0]["message"]["content"]
    else:
        raise Exception(f"Ошибка OpenRouter {response.status_code}: {response.text}")

# ============================================================
# 💼 ОБРАБОТКА НАКОПЛЕННЫХ СООБЩЕНИЙ
# ============================================================

async def process_delayed_reply(chat_id: int, business_connection_id: str, context: ContextTypes.DEFAULT_TYPE):
    # Ждем 6 секунд после твоего ПОСЛЕДНЕГО сообщения
    await asyncio.sleep(6.0)

    messages = PENDING_MESSAGES.pop(chat_id, [])
    PENDING_TASKS.pop(chat_id, None)

    if not messages:
        return

    combined_text = "\n".join(messages)

    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = []

    CHAT_HISTORY[chat_id].append({"role": "user", "content": combined_text})
    CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-10:]

    try:
        raw_answer = ask_ai(FIL_SYSTEM_PROMPT, CHAT_HISTORY[chat_id]).strip()
        clean_raw = raw_answer.replace("\n", " ")

        if "|||" in clean_raw:
            raw_parts = clean_raw.split("|||")
        else:
            raw_parts = re.split(r'(?<=[.!?]) +', clean_raw)

        messages_to_send = [p.strip() for p in raw_parts if p.strip()]
        full_assistant_reply = ""

        for part_text in messages_to_send:
            sticker_to_send = None

            match = re.search(r'\[STICKER:1\]', part_text)
            if match:
                if random.random() < 0.2:
                    sticker_to_send = STICKERS_MAP.get("1")
                part_text = re.sub(r'\[STICKER:1\]', '', part_text).strip()

            if not part_text and not sticker_to_send:
                continue

            # Показываем статус "печатает..." 2.5 секунды перед КАЖДЫМ сообщением
            await context.bot.send_chat_action(
                chat_id=chat_id, 
                action="typing", 
                business_connection_id=business_connection_id
            )
            
            # Реалистичная пауза печати (от 2 до 4 секунд)
            typing_delay = random.uniform(2.0, 3.5)
            await asyncio.sleep(typing_delay)

            if part_text:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=part_text,
                    business_connection_id=business_connection_id,
                )
                full_assistant_reply += part_text + " "

            if sticker_to_send:
                await asyncio.sleep(1.0)
                await context.bot.send_sticker(
                    chat_id=chat_id,
                    sticker=sticker_to_send,
                    business_connection_id=business_connection_id,
                )

            # Обязательный перерыв между отправкой отдельных сообщений (2–3 секунды)
            await asyncio.sleep(random.uniform(2.0, 3.0))

        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": full_assistant_reply.strip()})

    except Exception as e:
        print("\n❌ ОШИБКА BUSINESS:", repr(e))

# ============================================================
# 💼 BUSINESS MESSAGE
# ============================================================

async def handle_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.business_message:
        return

    msg = update.business_message
    chat_id = msg.chat.id
    user_text = msg.text or "[Медиа/Стикер]"

    # Реакция ❤️
    if random.random() < 0.4:
        try:
            await context.bot.set_message_reaction(
                chat_id=chat_id,
                message_id=msg.message_id,
                reaction=[ReactionTypeEmoji("❤️")],
            )
        except Exception as rx_err:
            print("⚠️ Ошибка реакции:", rx_err)

    if chat_id not in PENDING_MESSAGES:
        PENDING_MESSAGES[chat_id] = []
    PENDING_MESSAGES[chat_id].append(user_text)

    # Если ты написала еще одно сообщение — сбрасываем таймер и ждем заново!
    if chat_id in PENDING_TASKS:
        PENDING_TASKS[chat_id].cancel()

    # Запускаем таймаут ожидания на 6 секунд
    PENDING_TASKS[chat_id] = asyncio.create_task(
        process_delayed_reply(chat_id, msg.business_connection_id, context)
    )

async def handle_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    msg = update.message
    try:
        answer = ask_ai(FIL_SYSTEM_PROMPT, [{"role": "user", "content": msg.text}])
        clean_answer = answer.replace("|||", " ")
        await msg.reply_text(clean_answer)
    except Exception as e:
        print("\n❌ ОШИБКА DIRECT:", repr(e))

async def handle_business_connection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.business_connection:
        print(f"\n🔗 BUSINESS CONNECTION: ID {update.business_connection.id}")

async def handle_ping(request):
    return web.Response(text="Bot is live!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

async def main():
    await start_web_server()

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )

    app.add_handler(TypeHandler(Update, handle_business_connection), group=-2)
    app.add_handler(TypeHandler(Update, handle_business), group=-1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct))

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(
            allowed_updates=[
                "message",
                "business_message",
                "business_connection",
                "edited_business_message",
            ]
        )
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
