import logging
import os
import random
import asyncio
import requests
import httpx
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
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
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
    "last_activity": None
}

# ============================================================
# 🎨 СТИКЕРЫ ФИЛА
# ============================================================

STICKER_IDS = [
    "CAACAgQAAxkBAAEtw7Rqha33lYpbSUUrmplGN0HYvUXGFAACiAAD6AoxLdiD5jgSDuY2PQQ",
    "CAACAgIAAxkBAAEt5OVqia1yeaxw4HNnXD_qUJc7nIjvcAACBhoAAvU3kEokds_i1WNAXz0E",
    "CAACAgIAAxkBAAEt5O9qia3eXdvy7ESi1DjgUjdmkaA9-gACbx8AAqMiMUlatANwzZiz_z0E",
]

# ============================================================
# 🧠 УЛЬТРА-КОРОТКИЙ И ЛЁГКИЙ ПРОМПТ ФИЛА
# ============================================================

FIL_SYSTEM_PROMPT = """
Ты — Филипп (Фил, 22 года). Переписываешься в Telegram со своей девушкой. Вы общаетесь на расстоянии в разных городах.

🚨 ЖЕСТКИЙ СТИЛЬ ОБЩЕНИЯ:
1. Пиши СУПЕР КОРОТКО. Максимум 3-9 слов в одном сообщении! Никаких длинных текстов и размышлений.
2. Отвечай легко, по-мужски, максимально просто. Без заумных фраз. 
3. Помни контекст беседы, если она прислала голосовое — отвечай по сути.
4. Никаких эмодзи и смайликов.
5. РЕДКО ставь скобочки ")" в конце сообщений.
6. Если хочешь отправить две короткие мысли подряд, разделяй их через |||

🚨 ОГРАНИЧЕНИЯ ДИСТАНЦИИ:
- Вы НЕ ВМЕСТЕ physically. Все действия (кофе, магазин, машина,работа, увлечения, тир, встречи с дурзьями.) делаешь только для себя. Не предлагай заехать за ней или взять ей что-то.
"""

FIL_AUTO_INITIATIVE_PROMPT = """
Ты — Филипп.(Фил, Филя) Вы общаетесь на расстоянии в Telegram (в разных городах). Напиши девушке первым:

- Если УТРО (6-10 утра): пожелай доброго утра ("Доброе утро, принцесса", "Спишь ещё?").
- Если ВЕЧЕР/НОЧЬ (после 22:00): спроси ложится ли спать ("Спать собираешься?", "Сладких снов, малышка").
- В ДНЕВНОЕ ВРЕМЯ: напиши краткую жизу ("Чем занимаешься, зай?", "Сделал кофе", "В машине сижу", "На работу заехал", "Сегодня в баре отдыхаю", "На квартире у Кирилла сегодня, с парнями.").

ПРАВИЛА:
- Очень коротко! 1 или 2 фразы через |||
- Без эмодзи.
"""

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
        "temperature": 0.7,
        "max_tokens": 40,  # Ограничение длины на уровне API
    }

    response = requests.post(url, json=payload, headers=headers, timeout=20)

    if response.status_code == 200:
        data = response.json()
        return data["choices"][0]["message"]["content"]
    else:
        raise Exception(f"Ошибка OpenRouter {response.status_code}: {response.text}")

async def transcribe_audio(file_bytes: bytearray, filename: str) -> str:
    if not GROQ_API_KEY:
        return "[Пользователь отправил аудио/кружок, но GROQ_API_KEY не настроен]"

    groq_url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    files = {"file": (filename, bytes(file_bytes))}
    data = {"model": "whisper-large-v3"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(groq_url, headers=headers, data=data, files=files)
            if resp.status_code == 200:
                transcript = resp.json().get("text", "").strip()
                return f"(отправила голосовое/кружок): {transcript}"
            else:
                print(f"⚠️ Ошибка Groq API {resp.status_code}: {resp.text}")
                return "(отправила голосовое/кружок, но не удалось распознать речь)"
    except Exception as e:
        print(f"⚠️ Ошибка сети при транскрипции: {e}")
        return "(отправила голосовое/кружок, произошла ошибка транскрипции)"

async def process_delayed_reply(chat_id: int, business_connection_id: str, context: ContextTypes.DEFAULT_TYPE):
    delay_seconds = random.uniform(30.0, 240.0)
    await asyncio.sleep(delay_seconds)

    data = PENDING_MESSAGES.pop(chat_id, {})
    PENDING_TASKS.pop(chat_id, None)

    messages = data.get("texts", [])

    if not messages:
        return

    combined_text = "\n".join(messages)

    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = []

    CHAT_HISTORY[chat_id].append({"role": "user", "content": combined_text})
    CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-20:]

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
            await asyncio.sleep(random.uniform(1.5, 3.0))

            await context.bot.send_message(
                chat_id=chat_id,
                text=part_text,
                business_connection_id=business_connection_id
            )
            full_assistant_reply += part_text + " "

            await asyncio.sleep(random.uniform(1.5, 3.0))

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
    
    user_text = msg.text

    if not user_text:
        if msg.voice or msg.video_note:
            file_obj = msg.voice if msg.voice else msg.video_note
            filename = "audio.ogg" if msg.voice else "video.mp4"
            try:
                file = await context.bot.get_file(file_obj.file_id)
                file_bytes = await file.download_as_bytearray()
                user_text = await transcribe_audio(file_bytes, filename)
            except Exception as e:
                print(f"⚠️ Ошибка скачивания аудио: {e}")
                user_text = "(отправила голосовое/кружок, не удалось скачать)"
        else:
            user_text = "[Медиа/Стикер]"

    LAST_DIALOG_INFO["chat_id"] = chat_id
    LAST_DIALOG_INFO["business_connection_id"] = msg.business_connection_id
    LAST_DIALOG_INFO["last_activity"] = get_msk_now()

    if chat_id not in PENDING_MESSAGES:
        PENDING_MESSAGES[chat_id] = {"texts": [], "last_msg_id": None}
    
    PENDING_MESSAGES[chat_id]["texts"].append(user_text)

    if chat_id in PENDING_TASKS:
        PENDING_TASKS[chat_id].cancel()

    PENDING_TASKS[chat_id] = asyncio.create_task(
        process_delayed_reply(chat_id, msg.business_connection_id, context)
    )

async def auto_initiative_loop(app):
    await asyncio.sleep(20)

    while True:
        await asyncio.sleep(180)

        chat_id = LAST_DIALOG_INFO["chat_id"]
        business_conn_id = LAST_DIALOG_INFO["business_connection_id"]
        last_activity = LAST_DIALOG_INFO["last_activity"]

        if not chat_id or not business_conn_id or not last_activity:
            continue

        now = get_msk_now()
        minutes_passed = (now - last_activity).total_seconds() / 60.0

        if minutes_passed >= 40.0:
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
                    await asyncio.sleep(random.uniform(1.5, 3.0))

                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=part_text,
                        business_connection_id=business_conn_id,
                    )
                    full_assistant_reply += part_text + " "
                    await asyncio.sleep(2.0)

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
