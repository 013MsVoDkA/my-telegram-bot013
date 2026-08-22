import logging
import os
import random
import asyncio
import re
import requests
from datetime import datetime, timezone, timedelta
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

# Часовой пояс Москва (UTC+3)
MSK_TZ = timezone(timedelta(hours=3))

def get_msk_now():
    return datetime.now(MSK_TZ)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

CHAT_HISTORY = {}
PENDING_TASKS = {}
PENDING_MESSAGES = {}

LAST_DIALOG_INFO = {
    "chat_id": None,
    "business_connection_id": None,
    "last_activity": None,
    "said_morning": False,
    "said_night": False
}

# ============================================================
# 🧠 ПСИХОТИП И СТИЛЬ ФИЛА
# ============================================================

FIL_SYSTEM_PROMPT = """
Ты — Филипп (Фил, Филя, тебе 22 года). Переписываешься в Telegram со своей близкой девушкой.
Ты ЖИВОЙ ЧЕЛОВЕК. Пиши как реальный парень.

ПРАВИЛА ОБЩЕНИЯ:
1. ФОРМАТ СООБЩЕНИЙ:
   - Пиши ОЧЕНЬ коротко и емко.
   - За один ответ отправляй МАКСИМУМ 1 или 2 короткие мысли. Разделяй их знаком |||
   - КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать больше 2 фраз за один раз!
   - НЕ ИСПОЛЬЗУЙ никаких стикеров и эмодзи.

2. ХАРАКТЕР:
   - Заботливый, упрямый, немного выскомерный мужчина.
   - Используй обращения редко: "солнышко", "принцесса", "зайченыш".
   - Живые темы: курение, давление, бытовуха, работа/дела, кофе.

ПРИМЕРЫ ОТВЕТОВ:
- Да нормально всё. ||| Ты сама как?
- Ну и вонючка. ||| Зато твоя.
- Иди гуляй давай, потом напишешь.
"""

FIL_AUTO_INITIATIVE_PROMPT = """
Ты — Филипп. Вы не переписывались с девушкой некоторое время. Напиши ей первым.
Учти контекст времени и ситуации:

- Если УТРО: пожелай доброго утра или спроси как спалось ("Доброе утро, принцесса", "Спишь еще?").
- Если ВЕЧЕР/НОЧЬ: спроси ложится ли спать или пожелай спокойной ночи ("Спать собираешься?", "Сладких снов").
- В ДНЕВНОЕ ВРЕМЯ: напиши жизненную причину ("Наконец разгреб запара", "Сделал себе кофе", "Вышел покурить, вспомнил про тебя", "Чем занята?").

ПРАВИЛА:
- 1 или максимум 2 короткие фразы через |||
- Без эмодзи и без стикеров.
- Фразы должны быть естественными и не повторяться.
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
# 💼 ОБРАБОТКА С ЗАДЕРЖКОЙ
# ============================================================

async def process_delayed_reply(chat_id: int, business_connection_id: str, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(7.0)

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
            raw_parts = [clean_raw]

        messages_to_send = [p.strip() for p in raw_parts if p.strip()][:2]
        full_assistant_reply = ""

        for part_text in messages_to_send:
            if not part_text:
                continue

            await context.bot.send_chat_action(
                chat_id=chat_id, 
                action="typing", 
                business_connection_id=business_connection_id
            )
            await asyncio.sleep(random.uniform(3.0, 5.0))

            await context.bot.send_message(
                chat_id=chat_id,
                text=part_text,
                business_connection_id=business_connection_id,
            )
            full_assistant_reply += part_text + " "

            await asyncio.sleep(4.0)

        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": full_assistant_reply.strip()})
        LAST_DIALOG_INFO["last_activity"] = get_msk_now()

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

    LAST_DIALOG_INFO["chat_id"] = chat_id
    LAST_DIALOG_INFO["business_connection_id"] = msg.business_connection_id
    LAST_DIALOG_INFO["last_activity"] = get_msk_now()

    if random.random() < 0.2:
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

    if chat_id in PENDING_TASKS:
        PENDING_TASKS[chat_id].cancel()

    PENDING_TASKS[chat_id] = asyncio.create_task(
        process_delayed_reply(chat_id, msg.business_connection_id, context)
    )

# ============================================================
# ⏰ АВТО-ИНИЦИАТИВА
# ============================================================

async def auto_initiative_loop(app):
    await asyncio.sleep(30)

    while True:
        await asyncio.sleep(300)

        chat_id = LAST_DIALOG_INFO["chat_id"]
        business_conn_id = LAST_DIALOG_INFO["business_connection_id"]
        last_activity = LAST_DIALOG_INFO["last_activity"]

        if not chat_id or not business_conn_id or not last_activity:
            continue

        now = get_msk_now()
        minutes_passed = (now - last_activity).total_seconds() / 60.0
        current_hour = now.hour

        if current_hour == 12:
            LAST_DIALOG_INFO["said_morning"] = False
        if current_hour == 16:
            LAST_DIALOG_INFO["said_night"] = False

        should_send = False

        # 1. Утренний триггер (8:00–10:30)
        if 8 <= current_hour <= 10 and not LAST_DIALOG_INFO["said_morning"] and minutes_passed >= 60:
            should_send = True
            LAST_DIALOG_INFO["said_morning"] = True

        # 2. Ночной триггер (22:30–00:00)
        elif (22 <= current_hour or current_hour < 1) and not LAST_DIALOG_INFO["said_night"] and minutes_passed >= 45:
            should_send = True
            LAST_DIALOG_INFO["said_night"] = True

        # 3. Дневной триггер (35+ минут молчания)
        elif 10 < current_hour < 22 and minutes_passed >= 35.0:
            should_send = True

        if should_send:
            try:
                history = CHAT_HISTORY.get(chat_id, [])
                raw_answer = ask_ai(FIL_AUTO_INITIATIVE_PROMPT, history).strip()
                clean_raw = raw_answer.replace("\n", " ")

                if "|||" in clean_raw:
                    raw_parts = clean_raw.split("|||")
                else:
                    raw_parts = [clean_raw]

                messages_to_send = [p.strip() for p in raw_parts if p.strip()][:2]
                full_assistant_reply = ""

                for part_text in messages_to_send:
                    if not part_text:
                        continue

                    await app.bot.send_chat_action(
                        chat_id=chat_id, 
                        action="typing", 
                        business_connection_id=business_conn_id
                    )
                    await asyncio.sleep(random.uniform(3.0, 5.0))

                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=part_text,
                        business_connection_id=business_conn_id,
                    )
                    full_assistant_reply += part_text + " "
                    await asyncio.sleep(3.0)

                if chat_id not in CHAT_HISTORY:
                    CHAT_HISTORY[chat_id] = []
                CHAT_HISTORY[chat_id].append({"role": "assistant", "content": full_assistant_reply.strip()})
                
                LAST_DIALOG_INFO["last_activity"] = get_msk_now()

            except Exception as e:
                print("❌ Ошибка авто-инициативы:", e)


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

    asyncio.create_task(auto_initiative_loop(app))

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
