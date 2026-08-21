import logging
import random
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

import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# 🎭 БАЗА СТИКЕРОВ ФИЛА
STICKERS_LIST = [
    "CAACAgIAAxkBAAEtwulqhZxwMpsZOnbgHot-phjOyODN-AACno8AAq5I6UuVapKegpUePz0E",
    "CAACAgIAAxkBAAEtwxJqhaEr0BTu1z2sEv6j7Rkktd0-VQACiXwAAn_y2UiveLx-PFjtlD0E",
    "CAACAgIAAxkBAAEtwxpqhaFrrP0wRzZePLFtBik6xr23LgAC6BcAAowL2UiiSqB-xZy1vD0E",
    "CAACAgIAAxkBAAEtwxxqhaGQ92K8aiQnWyv0JX9UQdqY0AAC1gwAAoDJQEtXks0tYHcgDz0E",
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

CHAT_HISTORY = {}

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
    }

    response = requests.post(url, json=payload, headers=headers, timeout=20)

    if response.status_code == 200:
        data = response.json()
        return data["choices"][0]["message"]["content"]
    else:
        raise Exception(f"Ошибка OpenRouter {response.status_code}: {response.text}")


# ============================================================
# 💼 BUSINESS MESSAGE (Личка Telegram)
# ============================================================

async def handle_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.business_message:
        return

    msg = update.business_message
    chat_id = msg.chat.id
    user_text = msg.text or "[Отправил медиа/стикер]"

    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = []

    CHAT_HISTORY[chat_id].append({"role": "user", "content": user_text})
    CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-8:]

    print("\n==============================")
    print("🔥 BUSINESS MESSAGE ПОЛУЧЕНО!")
    print(f"От: {msg.from_user.first_name} (@{msg.from_user.username})")
    print("Текст:", user_text)
    print("==============================")

    # 🎲 РАНДОМ: 25% шанс, что Фил кинет стикер вместо текста
    if STICKERS_LIST and random.random() < 0.25:
        random_sticker = random.choice(STICKERS_LIST)
        await context.bot.send_sticker(
            chat_id=chat_id,
            sticker=random_sticker,
            business_connection_id=msg.business_connection_id,
        )
        print("✅ ОТПРАВЛЕН СТИКЕР!")
        return

    try:
        system_prompt = (
            "Ты — Филипп (Фил, Воягис Филипп Викторович). Переписываешься в Telegram со своей близкой подругой.\n\n"
            "ЖЕСТКИЕ ПРАВИЛА ОБЩЕНИЯ И АДАПТАЦИИ:\n"
            "1. ЗЕРКАЛЬ НАСТРОЕНИЕ И СТИЛЬ:\n"
            "   - Если тебе пишут ЛАСКОВО и МИЛО ('милый', 'зая', 'любимый', 'обнимаю') — отвечай взаимно, смущенно или тепло ('хех, ну ты чего', 'обнял тебя', 'целую', 'ты тоже милая', 'засмущала бля'). Никакой грубости и бычки на ласку!\n"
            "   - Если пишут спокойно/нейтрально — отвечай спокойно, адекватно и без агрессии.\n"
            "   - Если пишут агрессивно, с матом или наездами — только тогда отвечай дерзко и с наездом ('ты че ахуела', 'сама иди нах').\n"
            "   - Если заигрывают 18+ — отвечай прямо и дерзко ('трахну так что забудешь все', 'ща приеду раком поставлю').\n"
            "   - Если человеку плохо — включай заботу и поддержку ('ты че, не загоняйся', 'я рядом если че').\n"
            "2. ДЛИНА И СЛЕНГ: Пиши коротко (обычно 1-5 слов). Используй пацанский разговорный стиль ('понял', 'пон', 'забей', 'ага', 'хз', 'пхах', 'хех').\n"
            "3. МИНИМУМ СКОБОЧЕК: Очень редко используй скобочки ')' или '(('. Максимум 1 раз за несколько сообщений.\n"
            "4. НИКАКИХ ВОПРОСОВ: Не задавай вопросов в конце сообщений. Забудь знак '?'.\n"
            "5. ОФОРМЛЕНИЕ: Строго маленькие буквы, никаких точек в конце и знаков '!'.\n\n"
            "ПРИМЕРЫ РЕАКЦИЙ:\n"
            "Собеседник: милый!!\n"
            "Ты: хех ну че ты, обнял тебя\n\n"
            "Собеседник: зай я скучаю\n"
            "Ты: бля я тоже скучаю пиздец\n\n"
            "Собеседник: привет, чем занимаешься?\n"
            "Ты: да ниче, дома залипаю\n\n"
            "Собеседник: иди нахуй\n"
            "Ты: бля ты че ахуела, сама иди нах"
        )

        answer = ask_ai(system_prompt, CHAT_HISTORY[chat_id])

        answer_clean = (
            answer.lower()
            .replace("?", "")
            .replace("!", "")
            .replace(".", "")
            .strip()
        )

        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": answer_clean})

        await context.bot.send_message(
            chat_id=chat_id,
            text=answer_clean,
            business_connection_id=msg.business_connection_id,
        )
        print("✅ ОТВЕТ ОТПРАВЛЕН!")

    except Exception as e:
        print("\n❌ ОШИБКА BUSINESS:")
        print(repr(e))


async def handle_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    msg = update.message
    try:
        answer = ask_ai("Ты живой человек.", [{"role": "user", "content": msg.text}])
        await msg.reply_text(answer.lower().replace("!", "").replace("?", ""))
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

    print("\n==========================================")
    print("🤖 БОТ ЗАПУЩЕН И ГОТОВ К ОБЩЕНИЮ")
    print("==========================================")

    app.run_polling(
        allowed_updates=[
            "message",
            "business_message",
            "business_connection",
            "edited_business_message",
        ]
    )   