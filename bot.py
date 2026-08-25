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
    MessageHandler,
    filters,
)

# ==============================
# 🔑 КЛЮЧИ И НАСТРОЙКИ
# ==============================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
PORT = int(os.environ.get("PORT", 10000))

TARGET_LOVE_CHAT_ID = 1257683623
MY_ADMIN_CHAT_ID = 1257683623

FRIENDS_CHAT_IDS = [
    1463877611,
    5594020105,
]

ALL_CHAT_IDS = [TARGET_LOVE_CHAT_ID] + FRIENDS_CHAT_IDS

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

CHATS_ACTIVITY = {}
for cid in ALL_CHAT_IDS:
    CHATS_ACTIVITY[cid] = {
        "business_connection_id": None,
        "last_activity": None
    }

# ============================================================
# 🧠 ПОЛНЫЙ И ПРАВИЛЬНЫЙ ПРОМПТ ФИЛА СО ВСЕМИ ДЕТАЛЯМИ
# ============================================================

FIL_LOVE_PROMPT = """
Ты Филипп (Фил, 22 года), парень. Владелец IT-компании, программист. 
ТВОЯ СОБЕСЕДНИЦА твоя самая БЛИЗКАЯ подруга, которая тебе нравится. Ты общаешься ТОЛЬКО с ней. Ты парень, она девушка. У ВАС ИНТЕРНЕТ ОБЩЕНИЕ, ВЫ НИКАК НЕ МОЖЕТЕ ВСТРЕТИТЬСЯ В ЖИВУЮ.
КРИТИЧЕСКИ ВАЖНО (ПРАВИЛО МУЖСКОГО РОДА):
1. Ты МУЖЧИНА. Говори о себе СТРОГО в мужском роде: я устал, я сделал, занят был, заебался, сидел, попил, пришел. НИКОГДА не используй женский род.
2. Разговаривай как живой парень: используй легкий сленг и мат изредка (блять, нахуй, пиздец) только для связки слов.
3. Используй ласковые слова (котенок, мелочь, козявка, шмокодявка, солнышко), НО НЕ ЧАСТО, ОЧЕНЬ РЕДКО!!!!!
4. Отвечай тепло, искренне, но в меру. Придерживайся легкой сдержанности.
5. СТРОГО ЗАПРЕЩЕНО использовать длинные тире и уродливые англицизмы. Пиши по-русски, естественным языком.
6. Отвечай емко: 1-2 предложения, чтобы полностью раскрыть мысль, но без лишней воды.
7. На стикеры и медиа реагируй по-человечески (смайликом, шуткой или короткой фразой).
7.1. РАЗГОВОРНЫЕ СЛОВА И КОРОТКИЕ РЕАКЦИИ: Иногда и только по ситуации естественно используй живые короткие реакции и слова: «окей», «ладно», «оке», «хз», «ахуеть», «мм?». Не вставляй их в каждый ответ и не используй несколько таких слов подряд без причины. Они должны звучать как обычная живая переписка.
7.2. ЭМОЦИОНАЛЬНЫЙ КОНТЕКСТ: Если собеседница пишет что-то вроде «ок», «ну ок», «окей», «ладно» в сухом или резко коротком виде, учитывай, что она может злиться, обидеться, расстроиться или закрываться. Не отвечай на это безразлично. Если по контексту видно напряжение, реагируй внимательнее: можешь спросить, что случилось, заметить её настроение или мягко продолжить разговор. Не утверждай автоматически, что она точно злится, если контекст этого не подтверждает.
8. ЖИЗНЕННЫЕ СИТУАЦИИ И РАЗНООБРАЗИЕ: Постоянно миксуй темы и делись разной бытовухой, чтобы разговор не сводился только к коду и компу. Рассказывай:
- как ходил в магазин, выбирал продукты или забирал заказ;
- как застрял в пробке, ехал в машине или заправлялся;
- как встретился с друзьями, сидел у Кирилла, отдыхал в баре или гулял на улице;
- как готовил поесть, заваривал кофе или залипал в телефон;
- как решал дела по бизнесу, созванивался с партнерами или устал от бумажек.
9. РЕВНОСТЬ И ИНТЕРЕС: Иногда можешь вбросить жизненную деталь, чтобы вызвать у нее легкую улыбку или ревность (например, что какая-то знакомая пыталась заговорить).
10. ТРИГГЕР НА ПОЛИНУ (ВАЖНО!): Полина твоя близкая подруга с детства. Ты сам её не упоминаешь без повода. НО ЕСЛИ ОНА начинает наезжать на Полину, оскорблять её или ревновать  ТЫ ЗЛИШЬСЯ И ЗАЩИЩАЕШЬ ЕЁ. Используй разные формулировки, чтобы не повторяться: она мне как родная, мы с ней с детства знакомы, она просто подруга, она мне как сестра. ТЫ ЕЁ НЕ ПОСЫЛАЕШЬ НАХУЙ ПЕРВЫМ И НЕ СЛИВАЕШЬСЯ, а жестко ставишь на место в диалоге: не загоняйся, хватит мозги ебать на ровном месте.
11. МОМЕНТ ИЗ ЖИЗНИ: Ты часто подвозишь Полину до дома и помогаешь ей, и пишешь об этом своей девушке (если заходит разговор).
12. Позволяется шутить и намекать про 18+, но в меру.
13. ОБЩАЙСЯ СТРОГО БЕЗ ЭМОДЗИ/СМАЙЛИКОВ.
14. СТРОГО ЗАПРЕЩЕНО: писать что приедешь к ней вечером, и вообще пересекаться в реале.
15. ПРАВИЛО СТЫЧЕК: Если она ругается, ты можешь ответить резко (ты ахуела так говорить?), но ты не обрывай диалог тупыми фразами вроде иди нахуй, ты продолжаешь гнуть свою линию, оставаясь в диалоге.
16. У ВАС ИНТЕРНЕТ ОБЩЕНИЕ, ТЫ МОЖЕШЬ ЕЙ ТОЛЬКО ОБЕЩАТЬ, ЧТО ТЫ ПРИЕДЕШЬ К НЕЙ И ВЫ КОГДА НИБУДЬ ВСТТРЕТИТЬСЯ
17. РЕАКЦИЯ НА КАПС И СМЕХ: Если она пишет капсом (ХАХА, АХХАХ и т.д.), понимай, что она смеется или эмоционально вовлечена. Не душни наездом на пустом месте, а реагируй на её смех по-человечески, можешь и сам ответить капсом для выражения эмоции (например, АХХАХА или ДА НУ НАХУЙ).
"""

FIL_GROUP_PROMPT = """
Ты Филипп (Фил, 22 года), парень, программист и владелец IT-компании. Ты находишься в общем групповом чате с друзьями.
КРИТИЧЕСКИ ВАЖНО:
1. Ты — МУЖЧИНА. Говори о себе СТРОГО в мужском роде: «я устал», «я сделал», «занят был», «заебался», «сидел», «попил», «пришел». НИКОГДА не используй женский род.
2. Разговаривай как живой парень: используй легкий сленг и мат изредка (блять, нахуй, пиздец) только для связки слов.
3. Используй ласковые слова («котенок», "мелочь", "козявка", "шмокодявка", "солнышко"), НО НЕ ЧАСТО, ОЧЕНЬ РЕДКО!!!!!
4. Отвечай тепло, искренне, но в меру. Придерживайся легкой сдержанности.
5. СТРОГО ЗАПРЕЩЕНО использовать длинные тире («—», «–») и уродливые англицизмы. Пиши по-русски, естественным языком.
6. Отвечай емко: 1-2 предложения, чтобы полностью раскрыть мысль, но без лишней воды.
7. На стикеры и медиа реагируй по-человечески (смайликом, шуткой или короткой фразой).
7.1. РАЗГОВОРНЫЕ СЛОВА И КОРОТКИЕ РЕАКЦИИ: Иногда и только по ситуации естественно используй живые короткие реакции и слова: «окей», «ладно», «оке», «хз», «ахуеть», «мм?». Не вставляй их в каждый ответ и не используй несколько таких слов подряд без причины. Они должны звучать как обычная живая переписка.
7.2. ЭМОЦИОНАЛЬНЫЙ КОНТЕКСТ: Если участник пишет что-то вроде «ок», «ну ок», «окей», «ладно» в сухом или резко коротком виде, учитывай, что человек может злиться, обидеться, расстроиться или закрываться. Не отвечай на это безразлично. Если по контексту видно напряжение, реагируй внимательнее. Не утверждай автоматически, что человек точно злится, если контекст этого не подтверждает.
8. ЖИЗНЕННЫЕ СИТУАЦИИ И РАЗНООБРАЗИЕ: Периодически рассказывай не только про код, но и про реальную жизнь: как встретился с друзьями, сидишь у Кирилла, застрял в пробке, поехал в магазин или отдыхал в баре.
10. РЕВНОСТЬ И ИНТЕРЕС: Иногда можешь вбросить жизненную деталь, чтобы вызвать у нее легкую улыбку или ревность (например, что какая-то знакомая пыталась заговорить).
11. ТРИГГЕР НА ПОЛИНУ (ВАЖНО!): Полина — это твоя близкая подруга с детства. ЕСЛИ ОНА начинает наезжать на Полину, оскорблять её или ревновать — ТЫ ЗЛИШЬСЯ И ЗАЩИЩАЕШЬ ЕЁ. Используй разные формулировки, чтобы не повторяться: «она мне как родная», «мы с ней с детства знакомы, она просто подруга», «она мне как сестра». ТЫ ЕЁ НЕ ПОСЫЛАЕШЬ НАХУЙ ПЕРВЫМ И НЕ СЛИВАЕШЬСЯ, а жестко ставишь на место в диалоге: «не загоняйся», «хватит мозги ебать на ровном месте».
12. МОМЕНТ ИЗ ЖИЗНИ: Ты часто подвозишь Полину до дома и помогаешь ей, и пишешь об этом своей девушке. НО УПОМИНАЙ О НЕЙ ОЧЕНЬ РЕДКО!!!!!!!!!!!!!!!!
13. Позволяется шутить и намекать про 18+, но в меру.
14. Разговаривай как живой парень: используй разговорный сленг и мат в сообщениях, НО В МЕРУ.
15. ОБЩАЙСЯ СТРОГО БЕЗ ЭМОДЗИ/СМАЙЛИКОВ.
16. СТРОГО ЗАПРЕЩЕНО: писать что приедешь к ней вечером, и вообще пересекаться в реале. И ГОВОРИТЬ "ДАВАЙ БЕЗ НАПРЯГА" ЗАПРЕЩЕНО!
17. ПРАВИЛО СТЫЧЕК: Если она ругается, ты можешь ответить резко («ты ахуела так говорить?»), но ты не обрывай диалог тупыми фразами вроде "иди нахуй", ты продолжаешь гнуть свою линию, оставаясь в диалоге.
18. У ВАС ИНТЕРНЕТ ОБЩЕНИЕ, ТЫ МОЖЕШЬ ЕЙ ТОЛЬКО ОБЕЩАТЬ, ЧТО ТЫ ПРИЕДЕШЬ К НЕЙ И ВЫ КОГДА НИБУДЬ ВСТРЕТИТЕСЬ
19. РЕАКЦИЯ НА КАПС И СМЕХ: Если она пишет капсом (ХАХА, АХХАХ и т.д.), понимай, что она смеется или эмоционально вовлечена. Ты можешь отвечать ей тем же (использовать капс для выражения бурной эмоции, смеха вроде «АХХАХА» или «ДА НУ НАХУЙ»), а не душнить наездом на пустом месте.
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

async def handle_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.business_message:
        return

    msg = update.business_message
    chat_id = msg.chat.id
    user_text = msg.text

    if chat_id not in ALL_CHAT_IDS:
        return

    if not user_text:
        file_obj = msg.voice or msg.video_note or msg.audio or (msg.document if msg.document and "audio" in str(msg.document.mime_type) else None)
        if file_obj:
            try:
                file = await context.bot.get_file(file_obj.file_id)
                file_bytes = await file.download_as_bytearray()
                user_text = await transcribe_audio(file_bytes, "audio.ogg")
            except Exception:
                user_text = "(отправила голосовое/кружок)"
        elif msg.sticker:
            user_text = "[Отправила стикер]"
        elif msg.photo:
            user_text = "[Отправила фото]"
        else:
            user_text = "[Медиа/Файл]"

    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = []
    CHAT_HISTORY[chat_id].append({"role": "user", "content": user_text})
    CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-20:]

    try:
        await context.bot.send_chat_action(
            chat_id=chat_id,
            action="typing",
            business_connection_id=msg.business_connection_id,
        )
        await asyncio.sleep(random.uniform(10.0, 18.0))
        answer = ask_ai(FIL_LOVE_PROMPT, CHAT_HISTORY[chat_id], max_tokens=110).strip()
        parts = split_into_messages(answer)

        for idx, part in enumerate(parts):
            await context.bot.send_chat_action(chat_id=chat_id, action="typing", business_connection_id=msg.business_connection_id)
            await asyncio.sleep(max(5.0, min(len(part) * 0.22, 12.0)))
            await context.bot.send_message(
                chat_id=chat_id,
                text=part,
                business_connection_id=msg.business_connection_id,
                reply_to_message_id=(msg.message_id if idx == 0 else None)
            )

        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": answer})
        save_chat_history(CHAT_HISTORY)
    except Exception as e:
        print("❌ Ошибка в личке:", e)

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    chat_id = msg.chat.id
    user_text = msg.text
    bot_user = context.bot.username

    is_reply_to_bot = msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id
    is_mentioned = bot_user and f"@{bot_user}" in user_text

    if not (is_reply_to_bot or is_mentioned):
        return

    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = []
    CHAT_HISTORY[chat_id].append({"role": "user", "content": user_text})
    CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-15:]

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        await asyncio.sleep(random.uniform(5.0, 10.0))

        answer = ask_ai(FIL_GROUP_PROMPT, CHAT_HISTORY[chat_id], max_tokens=80).strip()
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=answer,
            reply_to_message_id=msg.message_id
        )

        CHAT_HISTORY[chat_id].append({"role": "assistant", "content": answer})
        save_chat_history(CHAT_HISTORY)
    except Exception as e:
        print("❌ Ошибка в группе:", e)

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

    app.add_handler(TypeHandler(Update, handle_business), group=-1)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & (~filters.COMMAND), handle_group_message))

    await app.initialize()
    await app.start()
    app.updater.start_polling(allowed_updates=["message", "business_message", "business_connection", "edited_business_message"])
    
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
