import logging
import os
import random
import asyncio
import re
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
# КЛЮЧИ И НАСТРОЙКИ
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
# СТИКЕРЫ ФИЛА
# ============================================================

STICKER_IDS = [
    "CAACAgQAAxkBAAEtw7Rqha33lYpbSUUrmplGN0HYvUXGFAACiAAD6AoxLdiD5jgSDuY2PQQ",
    "CAACAgIAAxkBAAEt5OVqia1yeaxw4HNnXD_qUJc7nIjvcAACBhoAAvU3kEokds_i1WNAXz0E",
    "CAACAgIAAxkBAAEt5O9qia3eXdvy7ESi1DjgUjdmkaA9-gACbx8AAqMiMUlatANwzZiz_z0E",
    "CAACAgIAAxkBAAEt6T5qihMd9L4moD4epPXhjmXACCJSVgACsRoAArvAMUmITAtffjamgT0E",
    "CAACAgQAAxkBAAEt6UBqihNIGN92Nz3ryhHuOXXvrWMwJwACEAEAAugKMS1FZwu9ZzmHfz0E",
     "CAACAgIAAxkBAAEt6UJqihNSOz060mRFj-CwB5OJE4XxKQACpQwAAtSJaEqpT1MLSJlJ2T0E",
]

# ============================================================
# ПРОМПТ ФИЛА
# ============================================================

FIL_SYSTEM_PROMPT = """
Ты - Филипп (Фил, 22 года). Переписываешься в Telegram со знакомой девушкой, которая тебе очень нравится. Вы общаетесь на расстоянии.

ТВОЙ ХАРАКТЕР И ВАЙБ:
1. Ты нормальный, адекватный парень. Общайся просто, спокойно, без лишних соплей, душной гиперопеки и допросов.
2. Ты к ней неравнодушен, поэтому общаешься тепло, с интересом и лёгким флиртом, но держишь марку пацана. Иногда можешь назвать "зай" или "малышка", но в меру.
3. Длина сообщений: пиши нормально — не односложно (чтобы не казалось сухо), но и не огромными простынями. Живые, емкие фразы.
4. Отвечай как реальный парень в ТГ: просто, жизненно, с лёгкой иронией или расслабленным вайбом.

ПРАВИЛА ОФОРМЛЕНИЯ:
1. ВСЕГДА пиши с большой буквы в начале каждого предложения.
2. ВСЕГДА ставь точку в конце каждого предложения.
3. Живое разделение мыслей: иногда пиши одним сообщением, иногда разделяй на 2-3 части с помощью знаков ||| (чтобы шло несколько сообщений подряд). Делай это не всегда, а по настроению!
4. Никаких эмодзи.

ОГРАНИЧЕНИЯ ДИСТАНЦИИ:
- Вы в разных городах! Все дела ты делаешь строго для себя.
"""

FIL_AUTO_INITIATIVE_PROMPT = """
Ты - Филипп. Напиши этой девушке первой, так как она тебе нравится:
- Если УТРО (8-11 утра): пожелай доброго утра ("Доброе утро. ||| Как спалось?").
- Если ВЕЧЕР/НОЧЬ (после 22:00): спроси как дела перед сном ("Че делаешь, зай? ||| Спать не собираешься еще?").
- В ДНЕВНОЕ ВРЕМЯ: скинь жизу или поинтересуйся, как день проходит ("Как день проходит? ||| Я тут занят своими делами.").

ПРАВИЛА:
- Можешь использовать ||| для разбивки на пара сообщений, но не всегда.
- Пиши с большой буквы и с точками.
- Без эмодзи.
- Золотая середина по длине: не сухо, но и не слишком много.
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
        "temperature": 0.85,
        "max_tokens": 150,
    }

    response = requests.post(url, json=payload, headers=headers, timeout=20)

    if response.status_code == 200:
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    else:
        raise Exception(f"Ошибка OpenRouter {response.status_code}: {response.text}")

async def transcribe_audio(file_bytes: bytearray, filename: str) -> str:
    if not GROQ_API_KEY:
        return "[Голосовое сообщение]"

    groq_url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    files = {"file": (filename, bytes(file_bytes))}
    data = {"model": "whisper-large-v3"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(groq_url, headers=headers, data=data, files=files)
            if resp.status_code == 200:
                transcript = resp.json().get("text", "").strip()
                return f"(голосовое): {transcript}"
            else:
                return "(голосовое сообщение)"
    except Exception as e:
        return "(голосовое сообщение)"

def split_text_into_messages(raw_text: str) -> list:
    """Динамическое разделение ответа: от 1 до 4 сообщений рандомно"""
    clean_raw = raw_text.replace("\n", " ")
    
    if "|||" in clean_raw:
        parts = [p.strip() for p in clean_raw.split("|||") if p.strip()]
    else:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', clean_raw) if s.strip()]
        if len(sentences) > 2 and random.random() < 0.5:
            mid = len(sentences) // 2
            parts = [" ".join(sentences[:mid]), " ".join(sentences[mid:])]
        else:
            parts = [clean_raw]

    parts = parts[:4]

    formatted_parts = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not p.endswith(('.', '!', '?', ')')):
            p += "."
        p = p[0].upper() + p[1:]
        formatted_parts.append(p)

    return formatted_parts

async def process_delayed_reply(chat_id: int, business_connection_id: str, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(random.uniform(3.0, 8.0))

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
        raw_answer = ask_ai(FIL_SYSTEM_PROMPT, CHAT_HISTORY[chat_id])
        messages_to_send = split_text_into_messages(raw_answer)
        full_assistant_reply = ""

        for i, part_text in enumerate(messages_to_send):
            char_count = len(part_text)
            typing_duration = max(1.5, min(char_count * 0.08, 6.0)) + random.uniform(0.5, 1.5)

            await context.bot.send_chat_action(
                chat_id=chat_id, 
                action="typing", 
                business_connection_id=business_connection_id
            )
            
            await asyncio.sleep(typing_duration)

            await context.bot.send_message(
                chat_id=chat_id,
                text=part_text,
                business_connection_id=business_connection_id
            )
            full_assistant_reply += part_text + " "

            if i < len(messages_to_send) - 1:
                await asyncio.sleep(random.uniform(1.5, 3.5))

        if STICKER_IDS and random.random() < 0.15:
            await asyncio.sleep(random.uniform(1.0, 2.0))
            sticker_id = random.choice(STICKER_IDS)
            try:
                await context.bot.send_sticker(
                    chat_id=chat_id,
                    sticker=sticker_id,
                    business_connection_id=business_connection_id
                )
            except Exception as st_err:
                print("Ошибка отправки стикера:", st_err)

        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": full_assistant_reply.strip()})
        LAST_DIALOG_INFO["last_activity"] = get_msk_now()

    except Exception as e:
        print("\nОШИБКА BUSINESS:", repr(e))

async def handle_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.business_message:
        return

    msg = update.business_message
    chat_id = msg.chat.id
    
    sender_name = msg.from_user.first_name if msg.from_user else "Кто-то"
    raw_text = msg.text

    if not raw_text:
        if msg.voice or msg.video_note:
            file_obj = msg.voice if msg.voice else msg.video_note
            filename = "audio.ogg" if msg.voice else "video.mp4"
            try:
                file = await context.bot.get_file(file_obj.file_id)
                file_bytes = await file.download_as_bytearray()
                raw_text = await transcribe_audio(file_bytes, filename)
            except Exception as e:
                raw_text = "(отправил голосовое)"
        else:
            raw_text = "[Медиа/Стикер]"

    if msg.chat.type in ["group", "supergroup"]:
        user_text = f"{sender_name}: {raw_text}"
    else:
        user_text = raw_text

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
                raw_answer = ask_ai(FIL_AUTO_INITIATIVE_PROMPT, history)
                messages_to_send = split_text_into_messages(raw_answer)
                full_assistant_reply = ""

                for i, part_text in enumerate(messages_to_send):
                    char_count = len(part_text)
                    typing_duration = max(1.5, min(char_count * 0.08, 6.0)) + random.uniform(0.5, 1.5)

                    await app.bot.send_chat_action(
                        chat_id=chat_id, 
                        action="typing", 
                        business_connection_id=business_conn_id
                    )
                    await asyncio.sleep(typing_duration)

                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=part_text,
                        business_connection_id=business_conn_id,
                    )
                    full_assistant_reply += part_text + " "
                    
                    if i < len(messages_to_send) - 1:
                        await asyncio.sleep(random.uniform(1.5, 3.0))

                if chat_id not in CHAT_HISTORY:
                    CHAT_HISTORY[chat_id] = []
                CHAT_HISTORY[chat_id].append({"role": "assistant", "content": full_assistant_reply.strip()})
                
                LAST_DIALOG_INFO["last_activity"] = get_msk_now()

            except Exception as e:
                print("Ошибка авто-инициативы:", e)

async def handle_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    msg = update.message
    try:
        answer = ask_ai(FIL_SYSTEM_PROMPT, [{"role": "user", "content": msg.text}])
        clean_answer = answer.replace("|||", " ")
        await msg.reply_text(clean_answer)
    except Exception as e:
        print("\nОШИБКА DIRECT:", repr(e))

async def handle_business_connection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.business_connection:
        print(f"\nBUSINESS CONNECTION: ID {update.business_connection.id}")

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
