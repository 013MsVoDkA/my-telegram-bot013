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
   - Обязательно разделяй ответ на 2, 3 или 4 коротких сообщения подряд.

2. ГРАММАТИКА:
   - Пиши грамотно, соблюдай пунктуацию, ставь заглавные буквы и точки/запятые.

3. ХАРАКТЕР:
   - Заботливый, романтичный, но ведешь себя больше как мужчина, который знает себе цену, но при этом готов забодиться о девушке.
   - Используй обращения, но редко: "солнышко", "принцесса", "зайченыш", "ангелок".
   - Живые темы: курение, скачки давления с детства, дела, шутки про 18 лет/замуж/Польшу, хакерство, простая бытовуха, планы на будущее, мечты про встречу, шутки про 18+.
   - В ответ на ласку — отвечай нежностью и теплом.
   - Иногда ты должен быть занят и отвечать сухо и коротко, но граммотно.

4. СТИКЕРЫ:
   - ВНИМАНИЕ: Стикеры используй КРАЙНЕ РЕДКО! Только если ситуация супер-милая или трогательная. В 90% ответов НЕ СТАВЬ стикеры вообще.
   - Если и решишь отправить стикер, вставь метку [STICKER:1] в самом конце самого последнего сообщения.

ПРИМЕРЫ ОТВЕТОВ:
- Привет, принцесса. ||| Ты как там?
- Да нормальное давление, скачет опять. ||| Сейчас чаю попью и норм.
- Забей, всё решим. ||| Я рядом.
- Хех, засмущала совсем. ||| Обнял тебя.
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
# 💼 BUSINESS MESSAGE
# ============================================================

async def handle_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.business_message:
        return

    msg = update.business_message
    chat_id = msg.chat.id
    user_text = msg.text or "[Медиа/Стикер]"

    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = []

    CHAT_HISTORY[chat_id].append({"role": "user", "content": user_text})
    CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-10:]

    try:
        # Реакция ❤️ с шансом 50%
        if random.random() < 0.5:
            await asyncio.sleep(random.uniform(0.3, 0.8))
            try:
                await context.bot.set_message_reaction(
                    chat_id=chat_id,
                    message_id=msg.message_id,
                    reaction=[ReactionTypeEmoji("❤️")],
                )
            except Exception as rx_err:
                print("⚠️ Ошибка реакции:", rx_err)

        await asyncio.sleep(random.uniform(0.8, 1.5))

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

            # Проверяем метку стикера
            match = re.search(r'\[STICKER:1\]', part_text)
            if match:
                # Дополнительный случайный фильтр в коде (стикер уйдет только с вероятностью 25%)
                if random.random() < 0.25:
                    sticker_to_send = STICKERS_MAP.get("1")
                part_text = re.sub(r'\[STICKER:1\]', '', part_text).strip()

            if not part_text and not sticker_to_send:
                continue

            await context.bot.send_chat_action(
                chat_id=chat_id, 
                action="typing", 
                business_connection_id=msg.business_connection_id
            )
            
            typing_time = max(0.4, len(part_text) * 0.05)
            await asyncio.sleep(min(typing_time, 1.5))

            if part_text:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=part_text,
                    business_connection_id=msg.business_connection_id,
                )
                full_assistant_reply += part_text + " "

            if sticker_to_send:
                await asyncio.sleep(0.3)
                await context.bot.send_sticker(
                    chat_id=chat_id,
                    sticker=sticker_to_send,
                    business_connection_id=msg.business_connection_id,
                )

            await asyncio.sleep(random.uniform(0.3, 0.7))

        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": full_assistant_reply.strip()})

    except Exception as e:
        print("\n❌ ОШИБКА BUSINESS:", repr(e))


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

# Микро-сервер для Render
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
