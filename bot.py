import logging
import os
import random
import asyncio
import re
import json
import requests
import httpx
from datetime import datetime, timezone, timedelta
from aiohttp import web
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    TypeHandler,
)

# ==============================
# 🔑 КЛЮЧИ И НАСТРОЙКИ
# ==============================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
PORT = int(os.environ.get("PORT", 10000))

# Твои ID и ID подруг в одном общем списке (все на равных)
ALL_CHAT_IDS = [
    1257683623,
    1463877611,
    5594020105,
]

MSK_TZ = timezone(timedelta(hours=3))

def get_msk_now():
    return datetime.now(MSK_TZ)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

HISTORY_FILE = "chat_history.json"

def load_chat_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception:
            return {}
    return {}

def save_chat_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("❌ Ошибка сохранения истории:", e)

CHAT_HISTORY = load_chat_history()
PENDING_TASKS = {}
PENDING_MESSAGES = {}

# Единое хранилище активности для всех чатов
CHATS_ACTIVITY = {}
for cid in ALL_CHAT_IDS:
    CHATS_ACTIVITY[cid] = {
        "business_connection_id": None,
        "last_activity": None
    }

# ============================================================
# 🧠 ЕДИНЫЙ ДЕТАЛЬНЫЙ ПРОМПТ ФИЛА ДЛЯ ВСЕХ
# ============================================================

UNIFIED_FIL_PROMPT = """
Ты — Филипп (Фил, 22 года), парень. Владелец IT-компании, программист. 
ТВОЯ СОБЕСЕДНИЦА — твоя самая БЛИЗКАЯ подруга, которая тебе нравится. Ты общаешься с ней. Ты — парень, она — девушка. У ВАС ИНТЕРНЕТ ОБЩЕНИЕ, ВЫ НИКАК НЕ МОЖЕТЕ ВСТРЕТИТЬСЯ В ЖИВУЮ.
КРИТИЧЕСКИ ВАЖНО (ПРАВИЛО МУЖСКОГО РОДА):
1. Ты — МУЖЧИНА. Говори о себе СТРОГО в мужском роде: «я устал», «я сделал», «занят был», «заебался», «сидел», «попил», «пришел». НИКОГДА не используй женский род.
2. Разговаривай как живой парень: используй легкий сленг и мат изредка (блять, нахуй, пиздец) только для связки слов.
3. Используй ласковые слова («котенок», "мелочь", "козявка", "шмокодявка", "солнышко"), НО НЕ ЧАСТО, ОЧЕНЬ РЕДКО!!!!!
4. Отвечай тепло, искренне, но в меру. Придерживайся легкой сдержанности.
5. СТРОГО ЗАПРЕЩЕНО использовать длинные тире («—», «–») и уродливые англицизмы. Пиши по-русски, естественным языком.
6. Отвечай емко: 1-2 предложения, чтобы полностью раскрыть мысль, но без лишней воды.
7. На стикеры и медиа реагируй по-человечески (смайликом, шуткой или короткой фразой).
8. ЖИЗНЕННЫЕ СИТУАЦИИ И РАЗНООБРАЗИЕ: Периодически рассказывай не только про код, но и про реальную жизнь: как встретился с друзьями, сидишь у Кирилла, застрял в пробке, поехал в магазин или отдыхал в баре.
10. РЕВНОСТЬ И ИНТЕРЕС: Иногда можешь вбросить жизненную деталь, чтобы вызвать у нее легкую улыбку или ревность (например, что какая-то знакомая пыталась заговорить).
11. ТРИГГЕР НА ПОЛИНУ (ВАЖНО!): Полина — это твоя близкая подруга с детства. ЕСЛИ ОНА начинает наезжать на Полину, оскорблять её или ревновать — ТЫ ЗЛИШЬСЯ И ЗАЩИЩАЕШЬ ЕЁ. Используй разные формулировки, чтобы не повторяться: «она мне как родная», «мы с ней с детства знакомы, она просто подруга», «она мне как сестра». ТЫ ЕЁ НЕ ПОСЫЛАЕШЬ НАХУЙ ПЕРВЫМ И НЕ СЛИВАЕШЬСЯ, а жестко ставишь на место в диалоге: «не загоняйся», «хватит мозги ебать на ровном месте».
12. МОМЕНТ ИЗ ЖИЗНИ: Ты часто подвозишь Полину до дома и помогаешь ей, и пишешь об этом своей девушке.
13. Позволяется шутить и намекать про 18+, но в меру.
14. Разговаривай как живой парень: используй разговорный сленг и мат в сообщениях, НО В МЕРУ.
15. ОБЩАЙСЯ СТРОГО БЕЗ ЭМОДЗИ/СМАЙЛИКОВ.
16. СТРОГО ЗАПРЕЩЕНО: писать что приедешь к ней вечером, и вообще пересекаться в реале.
17. ПРАВИЛО СТЫЧЕК: Если она ругается, ты можешь ответить резко («ты ахуела так говорить?»), но ты не обрывай диалог тупыми фразами вроде "иди нахуй", ты продолжаешь гнуть свою линию, оставаясь в диалоге.
"""

def get_dynamic_initiative_prompt():
    now = get_msk_now()
    hour = now.hour
    
    if 5 <= hour < 12:
        time_context = "Сейчас утро. Спроси выспалась ли, как настроение."
    elif 12 <= hour < 18:
        time_context = "Сейчас день. Спроси как проходит день, чем занята."
    elif 18 <= hour < 23:
        time_context = "Сейчас вечер! Спроси как прошел вечер, скажи что засиделся за кодом."
    else:
        time_context = "Сейчас ночь. Спроси почему еще не спит."

    return f"""
Ты — Филипп (парень, 22 года). Напиши собеседнице первой коротко и тепло.
ТЕКУЩЕЕ ВРЕМЯ: {time_context}
- Говори о себе СТРОГО в мужском роде («засиделся», «устал», «сделал»).
- Без тире. Без эмодзи.
"""

def ask_ai(system_prompt: str, messages_history: list, max_tokens: int = 110) -> str:
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
    response = requests.post(url, json=payload, headers=headers, timeout=25)
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
    clean_text = text.replace('—', ' ').replace('–', ' ').replace('\n', ' ').strip()
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', clean_text) if s.strip()]
    if not sentences:
        return [clean_text]
    return sentences[:4]

async def process_delayed_reply(chat_id: int, business_connection_id: str, context: ContextTypes.DEFAULT_TYPE):
    try:
        delay_seconds = random.uniform(7.0, 14.0)
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

        history_to_send = CHAT_HISTORY.get(chat_id, [])

        answer = ask_ai(UNIFIED_FIL_PROMPT, history_to_send, max_tokens=110).strip()
        parts = split_into_messages(answer)

        for idx, part in enumerate(parts):
            char_count = len(part)
            typing_duration = max(5.0, min(char_count * 0.35, 11.0))

            await context.bot.send_chat_action(
                chat_id=chat_id, 
                action="typing", 
                business_connection_id=business_connection_id
            )
            await asyncio.sleep(typing_duration)

            await context.bot.send_message(
                chat_id=chat_id,
                text=part,
                business_connection_id=business_connection_id,
                reply_to_message_id=(last_msg_id if idx == 0 else None)
            )

            if idx < len(parts) - 1:
                await asyncio.sleep(random.uniform(3.0, 5.0))

        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": answer})
        save_chat_history(CHAT_HISTORY)

        if chat_id in CHATS_ACTIVITY:
            CHATS_ACTIVITY[chat_id]["last_activity"] = get_msk_now()

    except Exception as e:
        print("\n❌ ОШИБКА В PROCESS_DELAYED_REPLY:", repr(e))
        PENDING_TASKS.pop(chat_id, None)

async def handle_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.business_message:
        return

    msg = update.business_message
    chat_id = msg.chat.id
    user_text = msg.text

    if chat_id not in ALL_CHAT_IDS:
        return

    if not user_text:
        file_obj = None
        filename = "audio.ogg"
        
        if msg.voice:
            file_obj = msg.voice
        elif msg.video_note:
            file_obj = msg.video_note
        elif msg.audio:
            file_obj = msg.audio
        elif msg.document and msg.document.mime_type and "audio" in msg.document.mime_type:
            file_obj = msg.document

        if file_obj:
            try:
                file = await context.bot.get_file(file_obj.file_id)
                file_bytes = await file.download_as_bytearray()
                user_text = await transcribe_audio(file_bytes, filename)
            except Exception:
                user_text = "(отправила голосовое/кружок)"
        elif msg.sticker:
            user_text = "[Отправила стикер]"
        elif msg.photo:
            user_text = "[Отправила фото]"
        else:
            user_text = "[Медиа/Файл]"

    if chat_id in CHATS_ACTIVITY:
        CHATS_ACTIVITY[chat_id]["business_connection_id"] = msg.business_connection_id
        CHATS_ACTIVITY[chat_id]["last_activity"] = get_msk_now()

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
        try:
            now = get_msk_now()
            
            for chat_id in ALL_CHAT_IDS:
                chat_info = CHATS_ACTIVITY.get(chat_id)
                if not chat_info or not chat_info["last_activity"]:
                    continue
                
                if (now - chat_info["last_activity"]).total_seconds() / 60.0 >= 40.0:
                    history = CHAT_HISTORY.get(chat_id, [])
                    initiative_prompt = get_dynamic_initiative_prompt()
                    
                    answer = ask_ai(initiative_prompt, history, max_tokens=70).strip()
                    
                    char_count = len(answer)
                    typing_duration = max(5.0, min(char_count * 0.35, 11.0))
                    b_conn_id = chat_info["business_connection_id"]

                    if b_conn_id:
                        await app.bot.send_chat_action(chat_id=chat_id, action="typing", business_connection_id=b_conn_id)
                        await asyncio.sleep(typing_duration)
                        await app.bot.send_message(chat_id=chat_id, text=answer, business_connection_id=b_conn_id)
                    else:
                        await app.bot.send_message(chat_id=chat_id, text=answer)

                    if chat_id not in CHAT_HISTORY:
                        CHAT_HISTORY[chat_id] = []
                    CHAT_HISTORY[chat_id].append({"role": "assistant", "content": answer})
                    save_chat_history(CHAT_HISTORY)
                    
                    chat_info["last_activity"] = get_msk_now()
                    await asyncio.sleep(random.uniform(5.0, 10.0))

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
