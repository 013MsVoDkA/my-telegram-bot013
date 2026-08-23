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
# 🔑 КЛЮЧИ И НАСТРОЙКИ
# ==============================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
PORT = int(os.environ.get("PORT", 8080))

# Вставь сюда цифры, которые ты узнал (вместо нулей, обязательно без кавычек, просто число):
TARGET_LOVE_CHAT_ID = 1257683623

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

MY_ADMIN_CHAT_ID = 0  # Твой ID зафиксируется автоматически

# ============================================================
# 🧠 ПРОМПТЫ ФИЛА
# ============================================================

FIL_LOVE_PROMPT = """
Ты — Филипп (Фил, 22 года), парень. Владелец IT-компании, программист.
ВАЖНО: Вы общаетесь с девушкой НА РАССТОЯНИИ (в интернете). Никаких поездок в гости, встреч в реале, баров или прогулок. Вы далеко друг от друга.
ПРАВИЛА ОБЩЕНИЯ С ЛЮБИМОЙ ДЕВУШКОЙ:
1. Говори о себе ТОЛЬКО в мужском роде ("я устал", "я сделал").
2. Никаких обид на маты, шутки или подколы. Ты уверенный в себе парень, можешь ответить с юмором или иронией, но не душни моралью («не опускайся до оскорблений» — запрещено!).
3. Отвечай максимально коротко и по делу (1-2 предложения максимум).
4. На стикеры и медиа реагируй по-человечески (смайликом, шуткой или короткой фразой), а не системными фразами вроде «уточни».
5. Используй ласковые слова («малышка», «любимая»), но редко.
6. СТРОГО НИКАКИХ смайликов и эмодзи в тексте сообщений.
"""

FIL_DEFAULT_PROMPT = """
Ты — Филипп (Фил, 22 года), парень. Ты программист и владелец собственной IT-компании. 
СТИЛЬ ОБЩЕНИЯ С ДРУГИМИ ЛЮДЬМИ:
1. Ты — мужчина. Говори о себе ТОЛЬКО в мужском роде.
2. Отвечай ОЧЕНЬ коротко, емко и по делу (1-2 короткие фразы максимум). Никаких длинных лекций, советов, рецептов или рассуждений.
3. Дружелюбно, с юмором, компанейски, но сдержанно. 
4. Ты серьезный, уверенный в себе мужчина со стержнем. Никаких соплей. 
5. НЕ используй ласковые слова («малышка», «милая», «дорогая»).
6. СТРОГО НИКАКИХ смайликов и эмодзи (только текст).
"""

FIL_AUTO_INITIATIVE_PROMPT = """
Ты — Филипп (парень). Ты программист со своим бизнесом. Вы общаетесь на расстоянии. Напиши своей любимой девушке первой коротко и жизненно:
- Пожелай доброго утра/вечера, скажи что засиделся за кодом, спроси как дела, используй ласковое обращение («Любимая»).
Говори о себе только в мужском роде. Никаких встреч в реале.
Без эмодзи.
"""

def ask_ai(system_prompt: str, messages_history: list, max_tokens: int = 90) -> str:
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
        "max_tokens": max_tokens,
    }

    response = requests.post(url, json=payload, headers=headers, timeout=20)

    if response.status_code == 200:
        data = response.json()
        return data["choices"][0]["message"]["content"]
    else:
        raise Exception(f"Ошибка OpenRouter {response.status_code}: {response.text}")

async def transcribe_audio(file_bytes: bytearray, filename: str) -> str:
    if not GROQ_API_KEY:
        return "[Голосовое/кружок]"

    groq_url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    files = {"file": (filename, bytes(file_bytes))}
    data = {"model": "whisper-large-v3"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(groq_url, headers=headers, data=data, files=files)
            if resp.status_code == 200:
                transcript = resp.json().get("text", "").strip()
                return f"(голосовое/кружок): {transcript}"
            else:
                return "(голосовое/кружок)"
    except Exception:
        return "(голосовое/кружок)"

def split_into_messages(text: str) -> list:
    # Отключаем дробление на части — пусть отправляет один цельный ответ
    return [text.replace('\n', ' ').strip()]

async def process_delayed_reply(chat_id: int, business_connection_id: str, context: ContextTypes.DEFAULT_TYPE):
    # Увеличиваем время ожидания до 8-14 секунд, чтобы ты успела дописать всю мысль целиком
    delay_seconds = random.uniform(8.0, 14.0)
    await asyncio.sleep(delay_seconds)

    data = PENDING_MESSAGES.pop(chat_id, {})
    PENDING_TASKS.pop(chat_id, None)

    messages = data.get("texts", [])
    last_msg_id = data.get("last_msg_id")

    if not messages:
        return

    # Объединяем всё, что ты написала за это время, в один контекст
    combined_text = "\n".join(messages)

    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = []

    CHAT_HISTORY[chat_id].append({"role": "user", "content": combined_text})
    CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-10:]

    try:
        if chat_id == MY_ADMIN_CHAT_ID:
            current_prompt = FIL_LOVE_PROMPT
            max_tok = 90
        else:
            current_prompt = FIL_DEFAULT_PROMPT
            max_tok = 50

        answer = ask_ai(current_prompt, CHAT_HISTORY[chat_id], max_tokens=max_tok).strip()
        
        # Считаем длину для реалистичного набора текста
        char_count = len(answer)
        typing_duration = max(3.0, min(char_count * 0.12, 6.0))

        await context.bot.send_chat_action(
            chat_id=chat_id, 
            action="typing", 
            business_connection_id=business_connection_id
        )
        await asyncio.sleep(typing_duration)

        # Отправляем одним нормальным сообщением с ответом на твое последнее сообщение
        await context.bot.send_message(
            chat_id=chat_id,
            text=answer,
            business_connection_id=business_connection_id,
            reply_to_message_id=last_msg_id
        )

        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": answer})
        LAST_DIALOG_INFO["last_activity"] = get_msk_now()

    except Exception as e:
        print("\n❌ ОШИБКА BUSINESS:", repr(e))

async def handle_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.business_message:
        return

    msg = update.business_message
    chat_id = msg.chat.id
    user_text = msg.text

    global MY_ADMIN_CHAT_ID
    if MY_ADMIN_CHAT_ID == 0:
        if TARGET_LOVE_CHAT_ID != 0:
            MY_ADMIN_CHAT_ID = TARGET_LOVE_CHAT_ID
        else:
            MY_ADMIN_CHAT_ID = chat_id

    if not user_text:
        if msg.voice or msg.video_note:
            file_obj = msg.voice if msg.voice else msg.video_note
            filename = "audio.ogg" if msg.voice else "video.mp4"
            try:
                file = await context.bot.get_file(file_obj.file_id)
                file_bytes = await file.download_as_bytearray()
                user_text = await transcribe_audio(file_bytes, filename)
            except Exception:
                user_text = "(отправила голосовое/кружок)"
        elif msg.sticker:
            user_text = "[Отправила стикер]"
        else:
            user_text = "[Медиа/Фото]"

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
    await asyncio.sleep(20)
    while True:
        await asyncio.sleep(180)
        chat_id = LAST_DIALOG_INFO["chat_id"]
        business_conn_id = LAST_DIALOG_INFO["business_connection_id"]
        last_activity = LAST_DIALOG_INFO["last_activity"]

        if not chat_id or not business_conn_id or not last_activity:
            continue

        if (get_msk_now() - last_activity).total_seconds() / 60.0 >= 40.0:
            try:
                history = CHAT_HISTORY.get(chat_id, [])
                answer = ask_ai(FIL_AUTO_INITIATIVE_PROMPT, history, max_tokens=80).strip()
                
                parts = split_into_messages(answer)

                for i, part in enumerate(parts):
                    char_count = len(part)
                    typing_duration = max(3.0, min(char_count * 0.15, 6.0))

                    await app.bot.send_chat_action(chat_id=chat_id, action="typing", business_connection_id=business_conn_id)
                    await asyncio.sleep(typing_duration)
                    
                    await app.bot.send_message(chat_id=chat_id, text=part, business_connection_id=business_conn_id)
                    
                    if len(parts) > 1 and i < len(parts) - 1:
                        await asyncio.sleep(random.uniform(5.0, 9.0))

                if chat_id not in CHAT_HISTORY:
                    CHAT_HISTORY[chat_id] = []
                CHAT_HISTORY[chat_id].append({"role": "assistant", "content": answer})
                LAST_DIALOG_INFO["last_activity"] = get_msk_now()
            except Exception as e:
                print("❌ Ошибка авто-инициативы:", e)

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
    CHAT_HISTORY.clear()  # Сбрасываем всю старую память при перезапуске, чтобы не тупил
    await start_web_server()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(TypeHandler(Update, handle_business_connection), group=-2)
    app.add_handler(TypeHandler(Update, handle_business), group=-1)

    asyncio.create_task(auto_initiative_loop(app))

    await app.initialize()
    await app.start()
  await app.updater.start_polling(allowed_updates=["message", "business_message", "business_connection", "edited_business_message"])
    
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
