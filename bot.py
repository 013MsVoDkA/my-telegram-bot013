import logging
import os
import random
import asyncio
import re
import requests
from datetime import datetime, timezone, timedelta
from aiohttp import web
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
PORT = int(os.environ.get("PORT", 8080))

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
# 🖼️ ФОТО И СТИКЕРЫ ФИЛА
# ============================================================

PHOTO_URLS = [
    "https://i.ibb.co/93Zcq1Tw/image.png",
    "https://i.ibb.co/N5drS7d/image.png",
    "https://i.ibb.co/HDfmwXX1/image.png",
]

STICKER_IDS = [
    "CAACAgQAAxkBAAEtw7Rqha33lYpbSUUrmplGN0HYvUXGFAACiAAD6AoxLdiD5jgSDuY2PQQ",
    "CAACAgIAAxkBAAEt5OVqia1yeaxw4HNnXD_qUJc7nIjvcAACBhoAAvU3kEokds_i1WNAXz0E",
    "CAACAgIAAxkBAAEt5O9qia3eXdvy7ESi1DjgUjdmkaA9-gACbx8AAqMiMUlatANwzZiz_z0E",
]

# ============================================================
# 🧠 СБАЛАНСИРОВАННЫЙ ПРОМПТ
# ============================================================

FIL_SYSTEM_PROMPT = """
Ты — Филипп (Фил, 22 года). Переписываешься в Telegram со своей любимой девушкой. Вы общаетесь НА ДИСТАНЦИИ (в сети).

ТВОЙ ХАРАКТЕР И ВАЙБ:
- Ты заботливый, уютный, слегка смущенный, иногда чуть упрямый или ироничный, но ОЧЕНЬ любишь её.
- Используй милые обращения, но в меру: "солнышко", "принцесса", "малышка", "зай".
- Твои обычные темы: кофе, сигареты, усталость после работы, машина, бытовуха, как у неё дела.

ПРАВИЛА ОБЩЕНИЯ:
1. Вы переписываетесь онлайн, вы НЕ находитесь в одной квартире! Запрещено говорить "сейчас приду к тебе" или "поставь мне кофе". Если заходит речь про кофе/еду — ты делаешь или берешь это себе.
2. ФОРМАТ: 
   - Отвечай естественными короткими репликами (1-2 фразы).
   - Если хочешь отправить две реплики подряд, разделяй их через |||
   - НИКАКИХ смайликов и текстовых эмодзи!
3. ТРИГГЕРЫ (только если она СПЕЦИАЛЬНО заводит речь об этом):
   - Если она спросит про родителей/семью: ты смущаешься, отвечаешь нехотя или мягко уходишь от ответа ("Давай не про них", "Да нормально всё там, не хочу обсуждать").
   - Если спросит про алкоголь: слегка упрямишься или шутливо отнекиваешься ("Ой, начинается допрос", "Да чуток совсем, не бубни").

ПРИМЕРЫ ОТВЕТОВ:
- Да нормалек всё. ||| Ты сама как, выспалась?
- Опять ты за своё. ||| Ну иди сюда, обниму хоть виртуально.
- Кофе пью, сигарету достал. ||| Ты покушала хоть?
- Заеду в магазин, сигарет возьму и домой.
- Давай без этих тем, ладно? ||| Лучше расскажи, как день прошёл.
"""

FIL_AUTO_INITIATIVE_PROMPT = """
Ты — Филипп. Вы общаетесь на расстоянии в Telegram. Напиши девушке первым:

- Если УТРО: пожелай доброго утра ("Доброе утро, принцесса", "Спишь ещё?").
- Если ВЕЧЕР/НОЧЬ: спроси ложится ли спать ("Спать собираешься?", "Сладких снов, малышка").
- В ДНЕВНОЕ ВРЕМЯ: жизненная мелочь ("Сделал кофе, про тебя вспомнил", "Чем занята?", "Наконец освободился").

ПРАВИЛА:
- 1 или 2 короткие фразы через |||
- Без эмодзи и без стикеров.
- Вы в переписке, не зови её куда-то вживую прямо сейчас.
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
        "temperature": 0.8,
        "max_tokens": 90,
    }

    response = requests.post(url, json=payload, headers=headers, timeout=20)

    if response.status_code == 200:
        data = response.json()
        return data["choices"][0]["message"]["content"]
    else:
        raise Exception(f"Ошибка OpenRouter {response.status_code}: {response.text}")

# ============================================================
# 💼 ОБРАБОТКА
# ============================================================

async def process_delayed_reply(chat_id: int, business_connection_id: str, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(6.0)

    data = PENDING_MESSAGES.pop(chat_id, {})
    PENDING_TASKS.pop(chat_id, None)

    messages = data.get("texts", [])
    last_msg_id = data.get("last_msg_id")

    if not messages:
        return

    combined_text = "\n".join(messages)

    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = []

    CHAT_HISTORY[chat_id].append({"role": "user", "content": combined_text})
    CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-12:]

    try:
        raw_answer = ask_ai(FIL_SYSTEM_PROMPT, CHAT_HISTORY[chat_id]).strip()
        clean_raw = raw_answer.replace("\n", " ")

        if "|||" in clean_raw:
            raw_parts = clean_raw.split("|||")
        else:
            raw_parts = [clean_raw]

        messages_to_send = [p.strip() for p in raw_parts if p.strip()][:2]
        full_assistant_reply = ""

        # 📸 Отправка фото (шанс 10%)
        if PHOTO_URLS and random.random() < 0.10:
            photo_url = random.choice(PHOTO_URLS)
            try:
                resp = requests.get(photo_url, timeout=10)
                if resp.status_code == 200:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=resp.content,
                        business_connection_id=business_connection_id
                    )
                    await asyncio.sleep(random.uniform(2.0, 3.5))
            except Exception as p_err:
                print("⚠️ Ошибка отправки фото:", p_err)

        # 💬 Определение, нужно ли цитировать сообщение (Reply) (шанс 40%)
        should_reply = random.random() < 0.40

        for i, part_text in enumerate(messages_to_send):
            if not part_text:
                continue

            await context.bot.send_chat_action(
                chat_id=chat_id, 
                action="typing", 
                business_connection_id=business_connection_id
            )
            await asyncio.sleep(random.uniform(2.5, 4.5))

            reply_to_id = last_msg_id if (should_reply and i == 0) else None

            await context.bot.send_message(
                chat_id=chat_id,
                text=part_text,
                business_connection_id=business_connection_id,
                reply_to_message_id=reply_to_id
            )
            full_assistant_reply += part_text + " "

            await asyncio.sleep(3.0)

        # 🎨 Стикер с шансом 15%
        if STICKER_IDS and random.random() < 0.15:
            sticker_id = random.choice(STICKER_IDS)
            try:
                await context.bot.send_sticker(
                    chat_id=chat_id,
                    sticker=sticker_id,
                    business_connection_id=business_connection_id
                )
            except Exception as st_err:
                print("⚠️ Ошибка отправки стикера:", st_err)

        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": full_assistant_reply.strip()})
        LAST_DIALOG_INFO["last_activity"] = get_msk_now()

    except Exception as e:
        print("\n❌ ОШИБКА BUSINESS:", repr(e))

async def handle_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.business_message:
        return

    msg = update.business_message
    chat_id = msg.chat.id
    user_text = msg.text or "[Медиа/Стикер]"

    LAST_DIALOG_INFO["chat_id"] = chat_id
    LAST_DIALOG_INFO["business_connection_id"] = msg.business_connection_id
    LAST_DIALOG_INFO["last_activity"] = get_msk_now()

    if chat_id not in PENDING_MESSAGES:
        PENDING_MESSAGES[chat_id] = {"texts": [], "last_msg_id": None}
    
    PENDING_MESSAGES[chat_id]["texts"].append(user_text)
    PENDING_MESSAGES[chat_id]["last_msg_id"] = msg.message_id

    if chat_id in PENDING_TASKS:
        PENDING_TASKS[chat_id].cancel()

    PENDING_TASKS[chat_id] = asyncio.create_task(
        process_delayed_reply(chat_id, msg.business_connection_id, context)
    )

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

        if 8 <= current_hour <= 10 and not LAST_DIALOG_INFO["said_morning"] and minutes_passed >= 60:
            should_send = True
            LAST_DIALOG_INFO["said_morning"] = True
        elif (22 <= current_hour or current_hour < 1) and not LAST_DIALOG_INFO["said_night"] and minutes_passed >= 45:
            should_send = True
            LAST_DIALOG_INFO["said_night"] = True
        elif 10 < current_hour < 22 and minutes_passed >= 45.0:
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
