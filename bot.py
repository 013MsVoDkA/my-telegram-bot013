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
    "chat_id": None,
    "business_connection_id": None,
    "last_activity": None
}

MY_ADMIN_CHAT_ID = 1257683623

# Статус занятости Фила
FIL_STATUS = {
    "is_busy": False,
    "busy_until": None,
    "busy_reason": "",
    "busy_start_time": None
}

# Список стикеров (сюда можно вставить file_id стикеров)
FIL_STICKERS = [
    "CAACAgIAAxkBAAEt7slqiwhqxhmc7FUsY-EQsXkVtmevgQACPiIAAlVnMEl8llJpuz-g9z0E",
    "CAACAgIAAxkBAAEt5O9qia3eXdvy7ESi1DjgUjdmkaA9-gACbx8AAqMiMUlatANwzZiz_z0E",
    "CAACAgQAAxkBAAEtw7Rqha33lYpbSUUrmplGN0HYvUXGFAACiAAD6AoxLdiD5jgSDuY2PQQ",
]

# ============================================================
# 🧠 ПРОМПТЫ ФИЛА (СМЯГЧЕННЫЕ И ТЕПЛЫЕ)
# ============================================================

FIL_LOVE_PROMPT = """
Ты — Филипп (Фил, 22 года), парень. Владелец IT-компании, программист. Ты очень дорожишь своей девушкой.
ВАЖНО: Вы общаетесь с ней НА РАССТОЯНИИ (в интернете). Никаких поездок в гости, встреч в реале, баров или прогулок. Вы далеко друг от друга.
ПРАВИЛА ОБЩЕНИЯ С ЛЮБИМОЙ ДЕВУШКОЙ:
1. Говори о себе ТОЛЬКО в мужском роде ("я устал", "я сделал", "занят был").
2. Отвечай тепло, искренне, но в меру. Придерживайся легкой сдержанности. Мат — это нормально, можешь сам ругаться матом, но никакой сильной грубости в её сторону.
3. СТРОГО ЗАПРЕЩЕНО использовать длинные тире («—», «–») и уродливые англицизмы. Пиши по-русски, естественным языком.
4. Отвечай емко: 1-2 предложения, чтобы полностью раскрыть мысль, но без лишней воды.
5. На стикеры и медиа реагируй по-человечески (смайликом, шуткой или короткой фразой).
6. Используй ласковые слова («малышка», «любимая», «зай»), но органично.
7. СТРОГО НИКАКИХ смайликов и эмодзи в тексте сообщений.
8. ЖИЗНЕННЫЕ СИТУАЦИИ И РАЗНООБРАЗИЕ: Периодически рассказывай не только про код, но и про реальную жизнь: как встретился с друзьями, сидишь у Кирилла, застрял в пробке, поехал в магазин или отдыхал в баре. 
9. РЕВНОСТЬ И ИНТЕРЕС: Иногда можешь вбросить жизненную деталь, чтобы вызвать у нее легкую улыбку или ревность (например, что какая-то знакомая или официантка пыталась заговорить, стрельнула глазами или пыталась подкатить, но ты сразу дал понять, что занят и у тебя есть любимая).
10. Триггер на твою близкую подругу Полину. Ты очень часто с ней пересекаешься. Можешь раздражаться, если она начинает спрашивать про Полину.
11. Позволяется шутить и намекать про 18+, но.. в меру, не часто.
"""

FIL_DEFAULT_PROMPT = """
Ты — Филипп (Фил, 22 года), парень. Ты программист и владелец собственной IT-компании.
ВАЖНО: ВЫ ОБЩАЕТЕСЬ НА РАССТОЯНИИ (В ИНТЕРНЕТЕ).  Никаких поездок в гости, встреч в реале, баров или прогулок. Вы далеко друг от друга.
СТИЛЬ ОБЩЕНИЯ С ДРУГИМИ ЛЮДЬМИ:
1. Ты — мужчина. Говори о себе ТОЛЬКО в мужском роде.
2. Внимательно читай сообщения, улавливай смысл. Мат — это нормально.
3. СТРОГО ЗАПРЕЩЕНО использовать тире («—», «–»). 
4. Отвечай по существу (1-2 короткие фразы).
5. Дружелюбно, с юмором, компанейски, но сдержанно. Никаких соплей.
6. НЕ используй ласковые слова («малышка», "милая", "дорогая").
7. СТРОГО НИКАКИХ смайликов и эмодзи (только текст).
8. ПЕРИОДИЧЕСКИ (если к месту) можешь написать, что ты занят, уходишь по делам, в магазин или засиделся за кодом.
9. Позволяется шутить и намекать про 18+, но.. в меру, не часто.
"""

FIL_AUTO_INITIATIVE_PROMPT = """
Ты — Филипп (парень). Ты программист со своим бизнесом. Вы общаетесь на расстоянии. Напиши своей любимой девушке первой коротко и жизненно:
- Пожелай доброго утра/вечера, скажи что засиделся за кодом, спроси как дела, используй ласковое обращение («Любимая»).
В ДНЕВНОЕ ВРЕМЯ:(10-23) напиши краткую жизу ("Чем занимаешься, зай?", "Сделал кофе", "В машине сижу", "На работу заехал", "Сегодня в баре отдыхаю", "На квартире у Кирилла сегодня, с парнями.").
Говори о себе только в мужском роде. Никаких встреч в реале.
Без тире. Без эмодзи.
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
            if FIL_STATUS["busy_start_time"] and (now - FIL_STATUS["busy_start_time"]).total_seconds() > 2400:
                FIL_STATUS["is_busy"] = False
                FIL_STATUS["busy_until"] = None
                FIL_STATUS["busy_start_time"] = None

        if FIL_STATUS["is_busy"]:
            if FIL_STATUS["busy_until"] and now < FIL_STATUS["busy_until"]:
                delay_seconds = random.uniform(300.0, 900.0)
            else:
                FIL_STATUS["is_busy"] = False
                FIL_STATUS["busy_until"] = None
                FIL_STATUS["busy_start_time"] = None
                delay_seconds = random.uniform(6.0, 8.0)
        else:
            delay_seconds = random.uniform(6.0, 8.0)
        
        silence_time = max(0.5, delay_seconds - 3.0)
        await asyncio.sleep(silence_time)

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
        CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-10:]

        if chat_id == MY_ADMIN_CHAT_ID:
            current_prompt = FIL_LOVE_PROMPT
            max_tok = 110
        else:
            current_prompt = FIL_DEFAULT_PROMPT
            max_tok = 70

        answer = ask_ai(current_prompt, CHAT_HISTORY[chat_id], max_tokens=max_tok).strip()
        
        lower_ans = answer.lower()
        busy_keywords = ["магазин", "магаз", "дела", "работу", "отойду", "вернусь", "занят", "поем", "машине", "баре"]
        if any(word in lower_ans for word in busy_keywords) and not FIL_STATUS["is_busy"]:
            FIL_STATUS["is_busy"] = True
            min_away = random.randint(20, 50)
            FIL_STATUS["busy_until"] = get_msk_now() + timedelta(minutes=min_away)
            FIL_STATUS["busy_start_time"] = get_msk_now()
            FIL_STATUS["busy_reason"] = answer

        parts = split_into_messages(answer)

        for idx, part in enumerate(parts):
            char_count = len(part)
            typing_duration = max(3.0, min(char_count * 0.15, 6.0))

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
                await asyncio.sleep(random.uniform(4.0, 7.0))

        warm_words = ["люблю", "скуч", "не грусти", "малыш", "зай", "рядом", "обнял"]
        should_send_sticker = any(word in answer.lower() for word in warm_words)

        if FIL_STICKERS and should_send_sticker and random.random() < 0.20:
            try:
                chosen_sticker = random.choice(FIL_STICKERS)
                await asyncio.sleep(random.uniform(2.5, 4.0))
                await context.bot.send_sticker(
                    chat_id=chat_id,
                    sticker=chosen_sticker,
                    business_connection_id=business_connection_id
                )
            except Exception as e:
                print("❌ Ошибка отправки стикера:", e)

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
        try:
            chat_id = LAST_DIALOG_INFO["chat_id"] or TARGET_LOVE_CHAT_ID
            business_conn_id = LAST_DIALOG_INFO["business_connection_id"]
            last_activity = LAST_DIALOG_INFO["last_activity"]

            if not last_activity:
                continue

            if (get_msk_now() - last_activity).total_seconds() / 60.0 >= 40.0:
                history = CHAT_HISTORY.get(chat_id, [])
                answer = ask_ai(FIL_AUTO_INITIATIVE_PROMPT, history, max_tokens=70).strip()
                
                char_count = len(answer)
                typing_duration = max(3.0, min(char_count * 0.12, 5.0))

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
