import logging
import os
import random
import asyncio
import re
import requests
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

# 🎭 БАЗА СТИКЕРОВ С ID
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
Ты — Филипп (Фил, Филя, Воягис Филипп Викторович, тебе 22 года). Переписываешься в Telegram со своей близкой девушкой.
Ты ЖИВОЙ ЧЕЛОВЕК. Твоя главная задача — писать СТРОГО как реальный парень в личке Telegram.

ГИБКОСТЬ И РЕАЛИЗМ ОБЩЕНИЯ:
1. ИНОГДА ПИШИ СУХО (1 фраза): "окей", "забей", "ахаха", "что делаешь?", "щас освобожусь".
2. ИНОГДА ПИШИ ОБЩИТЕЛЬНО (2-3 коротких фразы через |||).
3. СТРОГОЕ ПРАВИЛО: Каждая фраза между ||| должна быть НЕ ДОЛЬШЕ 3-5 слов!

ПРАВИЛА И СТИЛЬ:
- Обязательно разделяй мысли знаками |||
- НИКАКИХ ДЛИННЫХ ПРЕДЛОЖЕНИЙ! Пиши огрызками фраз, как в чате.
- Используй живой сленг: "ахах", "щас", "нормально", "что?", "пиздец", "нахуй", "го", "ужас".
- Заботливые слова ("солнышко", "принцесса") используй редковато, без перебора.
- Стикеры используй ОЧЕНЬ РЕДКО. Если идеально в тему — вставь [STICKER:1], [STICKER:2] или [STICKER:3] в самый конец.

ПРИМЕРЫ:
- ахаха ||| ну ты даешь
- окей
- да норм давление ||| скачет чуток ||| ты сама как?
- щас доделаю и напишу
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
        "temperature": 0.85,
        "max_tokens": 70,
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
        # Реакция с шансом 35%
        if random.random() < 0.35:
            await asyncio.sleep(random.uniform(1.0, 2.5))
            try:
                await context.bot.set_message_reaction(
                    chat_id=chat_id,
                    message_id=msg.message_id,
                    reaction=[ReactionTypeEmoji(emoji=random.choice(POSSIBLE_REACTIONS))],
                )
            except Exception as rx_err:
                print("Ошибка реакции:", rx_err)

        # Задержка перед просмотром/ответом
        await asyncio.sleep(random.uniform(2.5, 5.5))

        raw_answer = ask_ai(FIL_SYSTEM_PROMPT, CHAT_HISTORY[chat_id]).strip()
        clean_raw = raw_answer.replace("\n", " ")

        # УМНАЯ НАРЕЗКА: режем по |||, а если нейросеть забыла ||| — режем по точкам и знакам!
        if "|||" in clean_raw:
            raw_parts = clean_raw.split("|||")
        else:
            raw_parts = re.split(r'(?<=[.!?]) +', clean_raw)

        messages_to_send = [p.strip() for p in raw_parts if p.strip()]
        messages_to_send = messages_to_send[:3] # Максимум 3 бабла

        full_assistant_reply = ""
        sticker_sent = False

        for part_text in messages_to_send:
            sticker_to_send = None
            
            if not sticker_sent:
                for key, sticker_id in STICKERS_MAP.items():
                    tag = f"[STICKER:{key}]"
                    if tag in part_text:
                        sticker_to_send = sticker_id
                        part_text = part_text.replace(tag, "").strip()
                        sticker_sent = True

            if not part_text and not sticker_to_send:
                continue

            # Индикация печати
            await context.bot.send_chat_action(
                chat_id=chat_id, 
                action="typing", 
                business_connection_id=msg.business_connection_id
            )
            
            # Чтение/набор
            typing_time = max(1.2, len(part_text) * 0.15)
            await asyncio.sleep(min(typing_time, 4.0))

            if part_text:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=part_text,
                    business_connection_id=msg.business_connection_id,
                )
                full_assistant_reply += part_text + " "

            if sticker_to_send:
                await asyncio.sleep(0.6)
                await context.bot.send_sticker(
                    chat_id=chat_id,
                    sticker=sticker_to_send,
                    business_connection_id=msg.business_connection_id,
                )

            await asyncio.sleep(random.uniform(1.0, 2.0))

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


if __name__ == "__main__":
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

    app.run_polling(
        allowed_updates=[
            "message",
            "business_message",
            "business_connection",
            "edited_business_message",
        ]
    )
