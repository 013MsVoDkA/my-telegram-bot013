import logging
import os
import random
import asyncio
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
    "2": "CAACAgIAAxkBAAEtwxpqhaFrrP0wRzZePLFtBik6xr23LgAC6BcAAowL2UiiSqB-xZy1vD0E",
    "3": "CAACAgIAAxkBAAEtw6lqha2LcFzVrwmc-bPkyi7mlZTiaAAC8hMAAtfP8Ur1tJ_0V1OnzT0E",
}

# ❤️ СПИСОК РЕАКЦИЙ
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

ГИБКОСТЬ И РЕАЛИЗМ ОБЩЕНИЯ (ЧЕРЕДУЙ НАСТРОЕНИЕ):
1. ИНОГДА ПИШИ СУХО И ЕМКО (всего 1 короткое сообщение): "окей", "забудь", "ахаха", "посмотрим", "что делаешь?", "мм..", "щас освобожусь".
2. ИНОГДА ПИШИ ОБЩИТЕЛЬНО (2-3 коротких фразы через |||): по делу, с вопросом, подколом или мыслью.
3. ОДНО СООБЩЕНИЕ = 1–5 СЛОВ. Никаких длинных монологов и портянок текста!
4. НЕ ЗАБЫВАЙ ПРО ТОЧКИ В КОНЦЕ КАЖДОГО СООБЩЕНИЯ, ВСЕГДА!!!!!!

ПРАВИЛА И СТИЛЬ:
- Разделяй мысли только символом ||| (КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать переносы строк!).
- Используй живой сленг: "ахах", "щас", "норм", "что", "ппц", "кайф", "го".
- Заботливые и ласковые слова ("солнышко", "принцесса", "зайка", "ангелок","милая") используй УМЕРЕННО, не лепи их в каждый ответ.
- Живые темы: курение, скачки давления с детства, код, дела, шутки про 18 лет/замуж/Польшу, хакерство, повседневная жизнь.
- Стикеры используй ОЧЕНЬ РЕДКО. Если идеально в тему — вставь [STICKER:1], [STICKER:2] или [STICKER:3] в самый конец.

ПРИМЕРЫ ВАРИАНТОВ ОТВЕТА:
- ахаха ||| ну ты даешь
- окей.
- да нормальное давление, пойдет ||| ты сама как, солнышко?
- щас доделаю и напишу
- кайф ||| погнали
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
        "max_tokens": 80,
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
        # Ставим реакцию с вероятностью 35%
        if random.random() < 0.35:
            await asyncio.sleep(random.uniform(0.5, 1.2))
            chosen_reaction = random.choice(POSSIBLE_REACTIONS)
            try:
                await context.bot.set_message_reaction(
                    chat_id=chat_id,
                    message_id=msg.message_id,
                    reaction=[ReactionTypeEmoji(emoji=chosen_reaction)],
                )
            except Exception as rx_err:
                print("Ошибка при установке реакции:", rx_err)

        # Пауза перед стартом набора (1.0 - 2.5 сек)
        await asyncio.sleep(random.uniform(1.0, 2.5))

        raw_answer = ask_ai(FIL_SYSTEM_PROMPT, CHAT_HISTORY[chat_id]).strip()

        # Чистим переносы строк и режем по |||
        clean_raw = raw_answer.replace("\n", " ")
        messages_to_send = [part.strip() for part in clean_raw.split("|||") if part.strip()]

        # Максимум 3 бабла за один ответ
        messages_to_send = messages_to_send[:3]

        full_assistant_reply = ""
        sticker_sent = False

        for part_text in messages_to_send:
            sticker_to_send = None
            
            # Разрешаем не более 1 стикера на весь ответ
            if not sticker_sent:
                for key, sticker_id in STICKERS_MAP.items():
                    tag = f"[STICKER:{key}]"
                    if tag in part_text:
                        sticker_to_send = sticker_id
                        part_text = part_text.replace(tag, "").strip()
                        sticker_sent = True

            if not part_text and not sticker_to_send:
                continue

            # Имитация печати
            await context.bot.send_chat_action(
                chat_id=chat_id, 
                action="typing", 
                business_connection_id=msg.business_connection_id
            )
            
            typing_time = max(0.4, len(part_text) * 0.06)
            await asyncio.sleep(min(typing_time, 2.0))

            # Отправка текстовой реплики
            if part_text:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=part_text,
                    business_connection_id=msg.business_connection_id,
                )
                full_assistant_reply += part_text + " "

            # Отправка стикера
            if sticker_to_send:
                await asyncio.sleep(0.3)
                await context.bot.send_sticker(
                    chat_id=chat_id,
                    sticker=sticker_to_send,
                    business_connection_id=msg.business_connection_id,
                )

            # Короткая пауза между баблами (0.3 - 0.8 сек)
            await asyncio.sleep(random.uniform(0.3, 0.8))

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
