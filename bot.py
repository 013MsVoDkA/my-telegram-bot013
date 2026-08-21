import logging
import os
import random
import asyncio
import requests
from telegram import Update
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
    "1": "CAACAgIAAxkBAAEtwulqhZxwMpsZOnbgHot-phjOyODN-AACno8AAq5I6UuVapKegpUePz0E",
    "2": "CAACAgIAAxkBAAEtwxJqhaEr0BTu1z2sEv6j7Rkktd0-VQACiXwAAn_y2UiveLx-PFjtlD0E",
    "3": "CAACAgIAAxkBAAEtwxpqhaFrrP0wRzZePLFtBik6xr23LgAC6BcAAowL2UiiSqB-xZy1vD0E",
    "4": "CAACAgIAAxkBAAEtwxxqhaGQ92K8aiQnWyv0JX9UQdqY0AAC1gwAAoDJQEtXks0tYHcgDz0E",
}

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
Ты ЖИВОЙ ЧЕЛОВЕК. Твоя главная задача — писать СТРОГО как реальный парень в личке Telegram, а не как нейросеть.

ПРАВИЛА ОБЩЕНИЯ:
1. ДЛИНА И ДЕЛЕНИЕ НА СООБЩЕНИЯ:
   - Пиши короткими фразулями (по 3-7 слов).
   - Если хочешь отправить 2 или 3 сообщения подряд (как в реальном ТГ), разделяй их символом |||
   - Пример: "Привет, солнышко. ||| Ты как там? Всё хорошо?"

2. ГРАММАТИКА:
   - Пиши грамотно, соблюдай пунктуацию, ставь заглавные буквы и точки/запятые.

3. ХАРАКТЕР:
   - Заботливый, романтичный, но прямой пацан.
   - Используй обращения: "солнышко", "принцесса", "зайченыш", "ангелок".
   - Живые темы: курение, скачки давления с детства, дела, шутки про 18 лет/замуж/Польшу, хакерство.
   - В ответ на ласку — отвечай нежностью и теплом.

4. СТИКЕРАМ:
   - Если идеально подходит стикер, вставь метку [STICKER:1], [STICKER:2], [STICKER:3] или [STICKER:4] в конец нужной фразы.

ПРИМЕРЫ ОТВЕТОВ:
- "Привет, принцесса. ||| Ты как там?"
- "Да нормальное давление, скачет опять. ||| Сейчас чаю попью и норм."
- "Забей, всё решим. ||| Я рядом."
- "Хех, засмущала совсем. ||| Обнял тебя. [STICKER:1]"
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
        "max_tokens": 100,
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
        # Пауза перед "прочтением"
        await asyncio.sleep(random.uniform(2.0, 4.0))

        raw_answer = ask_ai(FIL_SYSTEM_PROMPT, CHAT_HISTORY[chat_id]).strip()

        # Разбиваем ответ на отдельные сообщения
        messages_to_send = raw_answer.split("|||")

        full_assistant_reply = ""

        for part in messages_to_send:
            part_text = part.strip()
            if not part_text:
                continue

            # Ищем стикер в конкретном кусочке
            sticker_to_send = None
            for key, sticker_id in STICKERS_MAP.items():
                tag = f"[STICKER:{key}]"
                if tag in part_text:
                    sticker_to_send = sticker_id
                    part_text = part_text.replace(tag, "").strip()

            # Имитация набора текста для текущего сообщения
            typing_time = max(1.2, len(part_text) * 0.1)
            await context.bot.send_chat_action(
                chat_id=chat_id, 
                action="typing", 
                business_connection_id=msg.business_connection_id
            )
            await asyncio.sleep(min(typing_time, 4.0))

            # Отправляем сообщение
            if part_text:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=part_text,
                    business_connection_id=msg.business_connection_id,
                )
                full_assistant_reply += part_text + " "

            # Если к сообщению прилагается стикер
            if sticker_to_send:
                await asyncio.sleep(1.0)
                await context.bot.send_sticker(
                    chat_id=chat_id,
                    sticker=sticker_to_send,
                    business_connection_id=msg.business_connection_id,
                )

            # Небольшая пауза перед следующим сообщением (будто допечатывает)
            await asyncio.sleep(random.uniform(1.0, 2.5))

        # Сохраняем итоговый ответ в историю
        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": full_assistant_reply.strip()})

    except Exception as e:
        print("\n❌ ОШИБКА BUSINESS:", repr(e))


async def handle_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    msg = update.message
    try:
        answer = ask_ai(FIL_SYSTEM_PROMPT, [{"role": "user", "content": msg.text}])
        clean_answer = answer.replace("|||", "\n")
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
