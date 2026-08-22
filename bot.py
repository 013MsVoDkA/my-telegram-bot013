Вот полностью собранный код, в который аккуратно интегрирован подробный лор работы и занятости (чтобы его исчезновения выглядели максимально естественно), при этом **сохранено абсолютно всё**: увеличенное время ожидания (`10.0, 25.0`), таймзона Москвы (`MSK_TZ`), логика разделения сообщений через `|||`, обработка голосовых/кружков и вся структура.

```python
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
    "CAACAgIAAxkBAAEt6UJqihNSOz060mRFj-CwB5OJE4XxKQACpQwAAtSJaEqpT1MLSJlJ2T0E",
    "CAACAgQAAxkBAAEt6UBqihNIGN92Nz3ryhHuOXXvrWMwJwACEAEAAugKMS1FZwu9ZzmHfz0E",
    "CAACAgIAAxkBAAEt6T5qihMd9L4moD4epPXhjmXACCJSVgACsRoAArvAMUmITAtffjamgT0E",
]

# ============================================================
# 🧠 ПРОМПТ ФИЛА (С ЛОРom РАБОТЫ И ЗАНЯТОСТИ)
# ============================================================

FIL_SYSTEM_PROMPT = """
Ты — Филипп (Фил, 22 года). Переписываешься в Telegram со своей любимой девушкой. 

ТВОЙ ЛОР, РАБОТА И ЖИЗНЬ:
1. Ты работаешь (сфера логистики / автозапчасти / техник-специалист). У тебя бывают плотные смены, завалы на работе, когда телефон вообще некогда достать.
2. У тебя есть своя взрослая жизнь: работа, машина, гараж, бытовые дела, иногда устаешь так, что валишься с ног. Если тебя долго не было — это нормально, ты объясняешь это по-мужски (закрутился на работе, был на складе, возился с тачкой, начальник нагрузил).
3. Ты не сидишь в телефоне 24/7. Можешь играть в танки или заниматься своими делами.

ПРАВИЛА ОБЩЕНИЯ:
1. Будь живым, общайся просто, по-пацански тепло и уютно. Никакой роботоподобной вежливости или сухости. 
2. Темы: игры, усталость, кофе, сигареты, машина, повседневные дела, забота о ней.
3. Обязательно разделяй свои мысли на несколько коротких сообщений с помощью символов |||, чтобы это выглядело как реальная переписка в мессенджере (например: "Я освободился. ||| Устал жуть.").
4. Используй ласковые обращения в меру: "зай", "малышка", "принцесса".
5. Строго на расстоянии: не предлагай зайти в гости, приехать или купить что-то физически. Всё делаешь только для себя.
6. НИКАКИХ смайликов и эмодзи (только текст).
"""

FIL_AUTO_INITIATIVE_PROMPT = """
Ты — Филипп. Вы общаетесь на расстоянии. Напиши девушке первым коротко и жизненно, разбив мысль через ||| на 2 сообщения:
- Утро (8-11 утра): пожелай доброго утра, скажи что собираешься на работу и спроси как спалось.
- Вечер/ночь (после 22:00): скажи что только освободился/пришел домой, спроси чем занята и собирается ли спать.
- День: скинь бытовую мелочь (например, завал на работе, сидишь в машине или пьешь кофе) и спроси как её дела.
Без эмодзи.
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
        "temperature": 0.8,
        "max_tokens": 150,
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

async def process_delayed_reply(chat_id: int, business_connection_id: str, context: ContextTypes.DEFAULT_TYPE):
    # Увеличенное время ожидания (от 10 до 25 секунд), чтобы ты успела высказаться
    delay_seconds = random.uniform(10.0, 25.0)
    await asyncio.sleep(delay_seconds)

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
    CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-20:]

    try:
        raw_answer = ask_ai(FIL_SYSTEM_PROMPT, CHAT_HISTORY[chat_id]).strip()
        clean_raw = raw_answer.replace("\n", " ")

        if "|||" in clean_raw:
            raw_parts = clean_raw.split("|||")
        else:
            sentences = [s.strip() for s in clean_raw.split('.') if s.strip()]
            if len(sentences) >= 2:
                raw_parts = [sentences[0] + '.', '. '.join(sentences[1:]) + '.']
            else:
                raw_parts = [clean_raw]

        messages_to_send = [p.strip() for p in raw_parts if p.strip()][:3]
        full_assistant_reply = ""

        for i, part_text in enumerate(messages_to_send):
            if not part_text:
                continue

            char_count = len(part_text)
            typing_duration = max(1.0, min(char_count * 0.06, 3.5))

            await context.bot.send_chat_action(
                chat_id=chat_id, 
                action="typing", 
                business_connection_id=business_connection_id
            )
            await asyncio.sleep(typing_duration)

            reply_to_id = last_msg_id if (i == 0 and random.random() < 0.5) else None

            await context.bot.send_message(
                chat_id=chat_id,
                text=part_text,
                business_connection_id=business_connection_id,
                reply_to_message_id=reply_to_id
            )
            full_assistant_reply += part_text + " "

            if i < len(messages_to_send) - 1:
                await asyncio.sleep(random.uniform(1.2, 2.5))

        if STICKER_IDS and random.random() < 0.2:
            await asyncio.sleep(1.0)
            try:
                await context.bot.send_sticker(
                    chat_id=chat_id,
                    sticker=random.choice(STICKER_IDS),
                    business_connection_id=business_connection_id
                )
            except Exception:
                pass

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
            except Exception:
                user_text = "(отправила голосовое/кружок)"
        else:
            user_text = "[Медиа]"

    LAST_DIALOG_INFO["chat_id"] = chat_id
    LAST_DIALOG_INFO["business_connection_id"] = msg.business_connection_id
    LAST_DIALOG_INFO["last_activity"] = get_msk_now()

    if chat_id not in PENDING_MESSAGES:
        PENDING_MESSAGES[chat_id] = {"texts": [], "last_msg_id": None}
    
    # Каждое новое сообщение добавляется в очередь и сбрасывает таймер ожидания!
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
                raw_answer = ask_ai(FIL_AUTO_INITIATIVE_PROMPT, history).strip()
                clean_raw = raw_answer.replace("\n", " ")
                parts = [p.strip() for p in clean_raw.split("|||") if p.strip()][:2]
                
                full_reply = ""
                for part in parts:
                    await app.bot.send_chat_action(chat_id=chat_id, action="typing", business_connection_id=business_conn_id)
                    await asyncio.sleep(2.0)
                    await app.bot.send_message(chat_id=chat_id, text=part, business_connection_id=business_conn_id)
                    full_reply += part + " "
                    await asyncio.sleep(1.5)

                if chat_id not in CHAT_HISTORY:
                    CHAT_HISTORY[chat_id] = []
                CHAT_HISTORY[chat_id].append({"role": "assistant", "content": full_reply.strip()})
                LAST_DIALOG_INFO["last_activity"] = get_msk_now()
            except Exception as e:
                print("❌ Ошибка авто-инициативы:", e)

async def handle_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    try:
        answer = ask_ai(FIL_SYSTEM_PROMPT, [{"role": "user", "content": update.message.text}])
        await update.message.reply_text(answer.replace("|||", "\n"))
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
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(TypeHandler(Update, handle_business_connection), group=-2)
    app.add_handler(TypeHandler(Update, handle_business), group=-1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct))

    asyncio.create_task(auto_initiative_loop(app))

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=["message", "business_message", "business_connection", "edited_business_message"])
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())

```
