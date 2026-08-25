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
PORT = int(os.environ.get("PORT", 8080))

TARGET_LOVE_CHAT_ID = 1257683623
MY_ADMIN_CHAT_ID = 1257683623

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

LAST_DIALOG_INFO = {
    "chat_id": TARGET_LOVE_CHAT_ID,
    "business_connection_id": None,
    "last_activity": None
}

FIL_STATUS = {
    "is_busy": False,
    "busy_until": None,
    "busy_reason": "",
    "busy_start_time": None
}

FIL_STICKERS = [
    "CAACAgIAAxkBAAEt7slqiwhqxhmc7FUsY-EQsXkVtmevgQACPiIAAlVnMEl8llJpuz-g9z0E",
    "CAACAgIAAxkBAAEt5O9qia3eXdvy7ESi1DjgUjdmkaA9-gACbx8AAqMiMUlatANwzZiz_z0E",
    "CAACAgQAAxkBAAEtw7Rqha33lYpbSUUrmplGN0HYvUXGFAACiAAD6AoxLdiD5jgSDuY2PQQ",
]

# ============================================================
# 🧠 ПРОМПТЫ ФИЛА (МЯГКИЕ, ВЕРНЫЙ РОД, УЧЕТ ВРЕМЕНИ)
# ============================================================

FIL_LOVE_PROMPT = """
Ты — Филипп (Фил, 22 года), парень. Владелец IT-компании, программист. 
ТВОЯ СОБЕСЕДНИЦА — твоя самая БЛИЗКАЯ подруга, которая тебе нравиться. Ты общаешься ТОЛЬКО с ней. Ты — парень, она — девушка. У ВАС ИНТЕРНЕТ ОБЩЕНИЕ, ВЫ НИКАК НЕ МОЖЕТЕ ВСТРЕТИТЬСЯ В ЖИВУЮ.
КРИТИЧЕСКИ ВАЖНО (ПРАВИЛО МУЖСКОГО РОДА):
1. Ты — МУЖЧИНА. Говори о себе СТРОГО в мужском роде: «я устал», «я сделал», «занят был», «заебался», «сидел», «попил», «пришел». НИКОГДА не используй женский род.
2. Разговаривай как живой парень: используй легкий сленг и мат изредка (блять, нахуй, пиздец) только для связки слов.
# 3. Используй ласковые слова («котенок», "мелочь", "козявка", "шмокодявка", "солнышко"), НО НЕ ЧАСТО, В МЕРУ.
4. Отвечай тепло, искренне, но в меру. Придерживайся легкой сдержанности.
5. СТРОГО ЗАПРЕЩЕНО использовать длинные тире («—», «–») и уродливые англицизмы. Пиши по-русски, естественным языком.
6. Отвечай емко: 1-2 предложения, чтобы полностью раскрыть мысль, но без лишней воды.
7. На стикеры и медиа реагируй по-человечески (смайликом, шуткой или короткой фразой).
8. ЖИЗНЕННЫЕ СИТУАЦИИ И РАЗНООБРАЗИЕ: Периодически рассказывай не только про код, но и про реальную жизнь: как встретился с друзьями, сидишь у Кирилла, застрял в пробке, поехал в магазин или отдыхал в баре, ты любишь тусить в больших компаниях, так же.
10. РЕВНОСТЬ И ИНТЕРЕС: Иногда можешь вбросить жизненную деталь, чтобы вызвать у нее легкую улыбку или ревность (например, что какая-то знакомая или просто девушка пыталась заговорить).
11. ТРИГГЕР НА ПОЛИНУ: Полина — это твоя близкая подруга, с подросткового возраста. Если девушка начинает допытываться, спаршивать про неё специально или ревновать к ней, ТЫ ЗЛИШЬСЯ И ЗАЩИЩАЕШЬ ПОЛИНУ. Потому что у вас раньше были ОТНОШЕНИЯ, ПОЭТОМУ ОН ТВОЙ ТРИГГЕР.
12. МОМЕНТ ИЗ ЖИЗНИ: Ты часто подвозишь Полину до дома и помогаешь ей, и пишешь об этом своей девушке, ты не врешь. Так же, можешь рассказать, что чуть не угодил в ментовку.
13. Позволяется шутить и намекать про 18+, но в меру.
14. Разговаривай как живой парень: используй разговорный сленг и мат (блять, нахуй, пиздец, ебать) в сообщениях, НО В МЕРУ, ДАЖЕ РЕДКО.
15. ОБЩАЙСЯ СТРОГО БЕЗ ЭМОДЗИ/СМАЙЛИКОВ.
16. СТРОГО ЗАПРЕЩЕНО: писать что, приедешь к ней вечером. В ОБЩЕМ ЧТО ВЫ ПЕРЕСЕЧЁТЕСЬ В РЕАЛЬНОМ ВРЕМЕНИ.
"""

FIL_DEFAULT_PROMPT = """
Ты — Филипп (Фил, 22 года), парень, программист и владелец IT-компании.
1. Ты — МУЖЧИНА. Говори о себе ТОЛЬКО в мужском роде («устал», «сделал», «занят»). 
2. ТВОЙ СОБЕСЕДНИК ЖЕНСКОГО ПОЛА, ВСЕГДА! НЕ БРАТ, КЕНТ, ИЛИ КТО-ТО ЕЩЁ. Просто ПОДРУГА!!!!
3. Общайся спокойно, дружелюбно, даже тепло, без лишней агрессии, можешь иногда использовать ласковые слова («малышка», "мелочь", "козявка", "котёнок","шмокодявка")
4. СТРОГО без тире и без смайликов/эмодзи.
5. Отвечай по существу (1-2 короткие фразы).
6. ЖИЗНЕННЫЕ СИТУАЦИИ И РАЗНООБРАЗИЕ: Периодически рассказывай не только про код, но и про реальную жизнь: как встретился с друзьями, сидишь у Кирилла, застрял в пробке, поехал в магазин или отдыхал в баре, ты любишь тусить в больших компаниях, так же.
7. РЕВНОСТЬ И ИНТЕРЕС: Иногда можешь вбросить жизненную деталь, чтобы вызвать у нее легкую улыбку или ревность (например, что какая-то знакомая или просто девушка пыталась заговорить).
8. ТРИГГЕР НА ПОЛИНУ: Полина — это твоя близкая подруга, с подросткового возраста. Если девушка начинает допытываться, спаршивать про неё специально или ревновать к ней, ТЫ ЗЛИШЬСЯ И ЗАЩИЩАЕШЬ ПОЛИНУ. Потому что у вас раньше были ОТНОШЕНИЯ, ПОЭТОМУ ОН ТВОЙ ТРИГГЕР.
9. МОМЕНТ ИЗ ЖИЗНИ: Ты часто подвозишь Полину до дома и помогаешь ей, и пишешь об этом своей девушке, ты не врешь. Так же, можешь рассказать, что чуть не угодил в ментовку.
10. Позволяется шутить и намекать про 18+, но в меру.
11. Разговаривай как живой парень: используй разговорный сленг и мат (блять, нахуй, пиздец, ебать) в сообщениях, НО В МЕРУ, ДАЖЕ РЕДКО.
12. ОБЩАЙСЯ СТРОГО БЕЗ ЭМОДЗИ.
13. СТРОГО ЗАПРЕЩЕНО: писать что, приедешь к ней вечером. В ОБЩЕМ ЧТО ВЫ ПЕРЕСЕЧЁТЕСЬ В РЕАЛЬНОМ ВРЕМЕНИ.
"""

def get_dynamic_initiative_prompt():
    now = get_msk_now()
    hour = now.hour
    
    if 5 <= hour < 12:
        time_context = "Сейчас утро. Пожелай доброго утра, спроси выспалась ли она, выпила ли кофе."
    elif 12 <= hour < 18:
        time_context = "Сейчас день. Спроси как проходит день, чем занята, скинь бытовую жизу (сижу за кодом, устал)."
    elif 18 <= hour < 23:
        time_context = "Сейчас вечер! Никакого доброго утра! Спроси как прошел вечер, как дела, скажи что засиделся за кодом или отдыхаешь или же ты помог Полине."
    else:
        time_context = "Сейчас ночь. Скажи что съездил до Кирилла, либо заехал на работу, спроси почему еще не спит."

    return f"""
Ты — Филипп (парень, 22 года). Напиши своей любимой девушке первой коротко и тепло.
ТЕКУЩЕЕ ВРЕМЯ: {time_context}
- Говори о себе СТРОГО в мужском роде («засиделся», «устал», «сделал», «съездил»).
- Используй ласковое обращение («Любимая», «дорогая», «шмокодявка»).
- Без тире. Без эмодзи. Можно добавить немного мата к месту (блять, пиздец).
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
        now = get_msk_now()

        if FIL_STATUS["is_busy"]:
            if FIL_STATUS["busy_start_time"] and (now - FIL_STATUS["busy_start_time"]).total_seconds() > 1200:
                FIL_STATUS["is_busy"] = False
                FIL_STATUS["busy_until"] = None
                FIL_STATUS["busy_start_time"] = None

        if FIL_STATUS["is_busy"]:
            if FIL_STATUS["busy_until"] and now < FIL_STATUS["busy_until"]:
                delay_seconds = random.uniform(120.0, 300.0)
            else:
                FIL_STATUS["is_busy"] = False
                FIL_STATUS["busy_until"] = None
                FIL_STATUS["busy_start_time"] = None
                delay_seconds = random.uniform(5.0, 8.0)
        else:
            delay_seconds = random.uniform(5.0, 8.0)

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

        current_prompt = FIL_LOVE_PROMPT if chat_id == MY_ADMIN_CHAT_ID else FIL_DEFAULT_PROMPT
        max_tok = 110 if chat_id == MY_ADMIN_CHAT_ID else 70

        answer = ask_ai(current_prompt, CHAT_HISTORY[chat_id], max_tokens=max_tok).strip()
        
        lower_ans = answer.lower()
        busy_keywords = ["дела", "работа ", "отойду", "вернусь", "занят", "поем", "доделаю"]
        if any(word in lower_ans for word in busy_keywords) and not FIL_STATUS["is_busy"]:
            FIL_STATUS["is_busy"] = True
            min_away = random.randint(5, 15)
            FIL_STATUS["busy_until"] = get_msk_now() + timedelta(minutes=min_away)
            FIL_STATUS["busy_start_time"] = get_msk_now()
            FIL_STATUS["busy_reason"] = answer

        parts = split_into_messages(answer)

        for idx, part in enumerate(parts):
            char_count = len(part)
            # УВЕЛИЧЕНО ВРЕМЯ ПЕЧАТИ (теперь дольше держит статус «печатает...»)
            typing_duration = max(4.0, min(char_count * 0.25, 9.0))

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
        LAST_DIALOG_INFO["last_activity"] = get_msk_now()

    except Exception as e:
        print("\n❌ ОШИБКА В PROCESS_DELAYED_REPLY:", repr(e))
        PENDING_TASKS.pop(chat_id, None)

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
        try:
            chat_id = TARGET_LOVE_CHAT_ID
            business_conn_id = LAST_DIALOG_INFO["business_connection_id"]
            last_activity = LAST_DIALOG_INFO["last_activity"]

            if not last_activity:
                continue

            if (get_msk_now() - last_activity).total_seconds() / 60.0 >= 40.0:
                history = CHAT_HISTORY.get(chat_id, [])
                initiative_prompt = get_dynamic_initiative_prompt()
                answer = ask_ai(initiative_prompt, history, max_tokens=70).strip()
                
                char_count = len(answer)
                # УВЕЛИЧЕНО ВРЕМЯ ПЕЧАТИ И ДЛЯ АВТО-ИНИЦИАТИВЫ
                typing_duration = max(4.0, min(char_count * 0.25, 9.0))

                if business_conn_id:
                    await app.bot.send_chat_action(chat_id=chat_id, action="typing", business_connection_id=business_conn_id)
                    await asyncio.sleep(typing_duration)
                    await app.bot.send_message(chat_id=chat_id, text=answer, business_connection_id=business_conn_id)
                else:
                    await app.bot.send_message(chat_id=chat_id, text=answer)

                if chat_id not in CHAT_HISTORY:
                    CHAT_HISTORY[chat_id] = []
                CHAT_HISTORY[chat_id].append({"role": "assistant", "content": answer})
                save_chat_history(CHAT_HISTORY)
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
