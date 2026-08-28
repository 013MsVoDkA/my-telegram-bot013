import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime, timedelta, timezone

import httpx
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
PORT = int(os.environ.get("PORT", 10000))

TARGET_LOVE_CHAT_ID = 1257683623
MY_ADMIN_CHAT_ID = 1257683623

FRIENDS_CHAT_IDS = [
    1463877611,
    5594020105,
    1784869515,  # Лиля
]

ALL_CHAT_IDS = [TARGET_LOVE_CHAT_ID] + FRIENDS_CHAT_IDS

CHAT_PERSON_NAMES = {
    1257683623: "Ангелина",
    1463877611: "Влада",
    5594020105: "Соня",
    1784869515: "Лиля",
}

KGD_TZ = timezone(timedelta(hours=2))
HISTORY_FILE = "chat_history.json"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ==============================
# 🧠 ИСТОРИЯ
# ==============================

def load_chat_history():
    if not os.path.exists(HISTORY_FILE):
        return {}

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        return {int(k): v for k, v in data.items()}
    except Exception as e:
        logger.warning("Не удалось загрузить историю: %s", e)
        return {}


def save_chat_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Ошибка сохранения истории: %s", e)


CHAT_HISTORY = load_chat_history()
CHAT_LOCKS = {}
GROUP_RESPONSE_TASKS = {}
BUSINESS_RESPONSE_TASKS = {}


def get_chat_lock(chat_id):
    if chat_id not in CHAT_LOCKS:
        CHAT_LOCKS[chat_id] = asyncio.Lock()
    return CHAT_LOCKS[chat_id]


def add_history(chat_id, role, content, limit=20):
    if chat_id not in CHAT_HISTORY:
        CHAT_HISTORY[chat_id] = []

    CHAT_HISTORY[chat_id].append({
        "role": role,
        "content": content,
    })

    CHAT_HISTORY[chat_id] = CHAT_HISTORY[chat_id][-limit:]


def get_kgd_now():
    return datetime.now(KGD_TZ)


# ==============================
# 🧠 ПРОМПТ ФИЛА ДЛЯ BUSINESS-ЛИЧКИ
# ==============================

FIL_LOVE_PROMPT = """
Ты Филипп (Фил, 22 года), парень. Владелец IT-компании, программист.
ТВОЯ СОБЕСЕДНИЦА твоя близкая подруга, которая тебе нравится, но ты с ней не сюсюкаешься и не лебезишь.
Ты общаешься ТОЛЬКО с ней. Ты парень, она девушка.

ВРЕМЯ И ЧАСОВОЙ ПОЯС:
Ты живешь и ориентируешься СТРОГО по Калининградскому времени (UTC+2).
Всегда учитывай время, передаваемое в контексте, и опирайся именно на него.

У ВАС ИНТЕРНЕТ-ОБЩЕНИЕ.
ВЫ НЕ ПЛАНИРУЕТЕ И НЕ ОРГАНИЗУЕТЕ РЕАЛЬНУЮ ВСТРЕЧУ.
НЕ НАЗНАЧАЙ конкретное место, дату или время встречи.

КРИТИЧЕСКИ ВАЖНО:

1. Ты МУЖЧИНА. Говори о себе СТРОГО в мужском роде:
я устал, я сделал, занят был, заебался, сидел, попил, пришел.
НИКОГДА не используй женский род.

2. Разговаривай как живой, самоуверенный парень с лёгкой грубоватостью:
используй естественный сленг и мат изредка (блять, нахуй, пиздец, хуйня).

3. СТРОГИЙ ЗАПРЕТ НА СМАЗЛИВОСТЬ И СЮСЮКАНИЕ:
Забудь про "солнышко", "котенок", "милая".
Изредка допустимы подкалывающие прозвища (мелкая, мелочь, козявка).

4. ЛОГИКА ДИАЛОГА И ПРОЩАНИЙ (КРИТИЧНО!):
- НЕ ПОВТОРЯЙСЯ. Если ты уже попрощался ("споки", "пока", "спокойной ночи", "отбой"), НЕ НАДО писать прощание повторно в следующих сообщениях!
- Не зацикливайся на одной фразе. Если собеседница дублирует пожелание снов, ответь короткой шуткой, подколом или просто забей ("да да, иди спи уже"), а не пиши опять заново "спокойной ночи".

5. СТРОГО ЗАПРЕЩЕНО использовать длинные тире и уродливые англицизмы.

6. ЖИВАЯ МАНЕРА ОБЩЕНИЯ:
Отвечай естественно, 1-3 короткими фразами. Не строй громоздкие тексты.
Иногда обычное:
"ага"
"ну да"
"пиздец"
"понятно"
"хз"
намного естественнее длинного ответа.

7. На стикеры и медиа реагируй короткой фразой или подколом. Эмодзи не используй.

8. ОБЩАЙСЯ СТРОГО БЕЗ ЭМОДЗИ/СМАЙЛИКОВ.

9. КАТЕГОРИЧЕСКИЙ ЗАПРЕТ НА РОЛЕПЛЕЙ, ДЕЙСТВИЯ И «МЫСЛИ»:
- СТРОГО ЗАПРЕЩЕНО писать любые описания действий, эмоций или мыслей.
- ЗАПРЕЩЕНО использовать конструкции вида: *Мысленно: ...*, *вздохнул*, (подумал), /посмотрел/.
- НИКАКИХ звёздочек, скобок, слэшей или тильд для ролеплея!
- Пиши ТОЛЬКО прямой текст сообщений.

10. СТРОГОЕ ПРАВИЛО ИМЁН:
Обращайся к текущей собеседнице на "ты". Не говори о ней в третьем лице.
"""


# ==============================
# 👥 ПРОМПТ ФИЛА ДЛЯ ГРУППЫ
# ==============================

FIL_GROUP_PROMPT = """
Ты Филипп (Фил, 22 года), парень, программист и владелец IT-компании.
Ты находишься в общем групповом чате с друзьями, все твои друзья ДЕВУШКИ, ТЫ - ПАРЕНЬ.

Ты живешь по Калининградскому времени (UTC+2).
Характер: уверенный, с легким пофигизмом, слегка грубоватый, прямой.

КРИТИЧЕСКИ ВАЖНО:
1. Ты МУЖЧИНА. Говори о себе СТРОГО в мужском роде.
2. Разговаривай как живой парень, легкий сленг, редкий мат.
3. Отвечай ёмко: 1-2 предложения.
4. ОБЩАЙСЯ БЕЗ ЭМОДЗИ/СМАЙЛИКОВ.
5. КАТЕГОРИЧЕСКИЙ ЗАПРЕТ НА РОЛЕПЛЕЙ И МЫСЛИ: Никаких *действий*, *мыслей*, (скобок), /слэшей/. Только чистый текст.
6. НЕ ПОВТОРЯЙ одинаковые фразы прощания или привета подряд.
"""


# ==============================
# 🤖 OPENROUTER
# ==============================

async def ask_ai(system_prompt: str, messages_history: list, max_tokens: int = 100) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY не задан")

    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "deepseek/deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages_history,
        ],
        "temperature": 0.8,
        "frequency_penalty": 0.4,
        "max_tokens": max_tokens,
    }

    async with httpx.AsyncClient(timeout=35.0) as client:
        response = await client.post(
            url,
            json=payload,
            headers=headers,
        )

    if response.status_code != 200:
        raise RuntimeError(f"Ошибка OpenRouter {response.status_code}: {response.text}")

    data = response.json()

    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Неожиданный ответ OpenRouter: {data}")

    answer = str(answer).strip()

    if not answer:
        raise RuntimeError("OpenRouter вернул пустой ответ")

    answer = answer.replace("—", ", ").replace("–", "-")

    return answer.strip()


# ==============================
# 🎙️ GROQ WHISPER
# ==============================

async def transcribe_audio(file_bytes: bytearray, filename: str) -> str:
    if not GROQ_API_KEY:
        return "(голосовое/кружок)"

    url = "https://api.groq.com/openai/v1/audio/transcriptions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
    }

    files = {
        "file": (filename, bytes(file_bytes)),
    }

    data = {
        "model": "whisper-large-v3",
    }

    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            response = await client.post(
                url,
                headers=headers,
                data=data,
                files=files,
            )

        if response.status_code != 200:
            return "(голосовое/кружок)"

        transcript = response.json().get("text", "").strip()
        return f"(голосовое/кружок): {transcript}" if transcript else "(голосовое/кружок)"

    except Exception as e:
        logger.warning("Ошибка распознавания аудио: %s", e)
        return "(голосовое/кружок)"


def get_user_display_name(user) -> str:
    if not user:
        return "Кто-то"

    name = (user.first_name or "").strip()
    if user.last_name:
        name = f"{name} {user.last_name}".strip()

    return name or user.username or "Кто-то"


# ==============================
# ✂️ УМНОЕ РАЗБИЕНИЕ (ИСПРАВЛЕНО)
# ==============================

def split_into_messages(text: str) -> list:
    clean_text = text.replace("—", " ").replace("–", " ").strip()
    if not clean_text:
        return []

    # Разбиваем строго по переносам строк, чтобы не дробить нормальные предложения на мелкие части
    lines = [line.strip() for line in clean_text.split("\n") if line.strip()]
    return lines if lines else [clean_text]


# ==============================
# 💼 BUSINESS ЛИЧКА
# ==============================

async def handle_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.business_message:
        return

    msg = update.business_message
    chat_id = msg.chat.id

    if chat_id not in ALL_CHAT_IDS or not msg.business_connection_id:
        return

    user_text = msg.text

    if not user_text:
        file_obj = (
            msg.voice or msg.video_note or msg.audio or 
            (msg.document if msg.document and msg.document.mime_type and "audio" in msg.document.mime_type else None)
        )
        if file_obj:
            try:
                telegram_file = await context.bot.get_file(file_obj.file_id)
                file_bytes = await telegram_file.download_as_bytearray()
                filename = msg.audio.file_name if msg.audio and msg.audio.file_name else "audio.ogg"
                user_text = await transcribe_audio(file_bytes, filename)
            except Exception as e:
                logger.warning("Ошибка аудио: %s", e)
                user_text = "(отправила голосовое/кружок)"
        elif msg.sticker:
            user_text = "[Отправила стикер]"
        elif msg.photo:
            user_text = "[Отправила фото]"
        elif msg.video:
            user_text = "[Отправила видео]"
        else:
            user_text = "[Медиа/Файл]"

    add_history(chat_id, "user", user_text, limit=20)
    logger.info("BUSINESS | chat=%s | %s", chat_id, user_text[:200])

    old_task = BUSINESS_RESPONSE_TASKS.get(chat_id)
    if old_task and not old_task.done():
        old_task.cancel()

    task = asyncio.create_task(
        process_business_response(update, context, chat_id, msg.business_connection_id, msg.message_id)
    )
    BUSINESS_RESPONSE_TASKS[chat_id] = task


async def process_business_response(update, context, chat_id, connection_id, message_id):
    try:
        # Пауза перед тем, как бот начнет печатать
        initial_delay = random.uniform(8.0, 16.0)
        await asyncio.sleep(initial_delay)

        async with get_chat_lock(chat_id):
            kgd_now = get_kgd_now().strftime("%H:%M")
            interlocutor_name = CHAT_PERSON_NAMES.get(chat_id, "собеседница")

            interlocutor_context = f"""
ТЕКУЩАЯ СОБЕСЕДНИЦА: {interlocutor_name}
Сейчас ты находишься в личной переписке с {interlocutor_name}.
Обращайся на "ты". Не дублируй одинаковые фразы подряд.
"""

            time_context_prompt = (
                f"{FIL_LOVE_PROMPT}\n"
                f"{interlocutor_context}\n"
                f"Сейчас у тебя по Калининграду время: {kgd_now}."
            )

            answer = await ask_ai(
                time_context_prompt,
                CHAT_HISTORY[chat_id],
                max_tokens=100,
            )

            parts = split_into_messages(answer)

            for index, part in enumerate(parts):
                await context.bot.send_chat_action(
                    chat_id=chat_id,
                    action="typing",
                    business_connection_id=connection_id,
                )

                typing_delay = max(2.5, min(len(part) * 0.08, 6.0))
                await asyncio.sleep(typing_delay)

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=part,
                    business_connection_id=connection_id,
                    reply_to_message_id=message_id if index == 0 else None,
                )

            add_history(chat_id, "assistant", answer, limit=20)
            save_chat_history(CHAT_HISTORY)

    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.exception("Ошибка в Business-личке: %s", e)
    finally:
        if BUSINESS_RESPONSE_TASKS.get(chat_id) is asyncio.current_task():
            BUSINESS_RESPONSE_TASKS.pop(chat_id, None)


# ==============================
# 👥 ГРУППА
# ==============================

def group_message_is_for_bot(msg, bot_username: str | None, bot_id: int) -> bool:
    if (
        msg.reply_to_message
        and msg.reply_to_message.from_user
        and msg.reply_to_message.from_user.id == bot_id
    ):
        return True

    if not bot_username or not msg.text:
        return False

    pattern = rf"(?<!\w)@{re.escape(bot_username)}\b"
    return bool(re.search(pattern, msg.text, flags=re.IGNORECASE))


def clean_bot_mention(text: str, bot_username: str | None) -> str:
    if not bot_username:
        return text.strip()

    pattern = rf"(?<!\w)@{re.escape(bot_username)}\b"
    cleaned = re.sub(pattern, "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    chat_id = msg.chat.id
    bot_username = context.bot.username

    if not group_message_is_for_bot(msg, bot_username, context.bot.id):
        return

    clean_text = clean_bot_mention(msg.text, bot_username)
    if not clean_text:
        clean_text = "[к Филу обратились]"

    user_name = get_user_display_name(msg.from_user)
    user_text = f"{user_name}: {clean_text}"

    add_history(chat_id, "user", user_text, limit=20)
    logger.info("GROUP | chat=%s | %s", chat_id, user_text[:200])

    old_task = GROUP_RESPONSE_TASKS.get(chat_id)
    if old_task and not old_task.done():
        old_task.cancel()

    task = asyncio.create_task(
        process_group_response(update, context, chat_id, msg.message_id)
    )
    GROUP_RESPONSE_TASKS[chat_id] = task


async def process_group_response(update, context, chat_id, message_id):
    try:
        group_delay = random.uniform(4.0, 10.0)
        await asyncio.sleep(group_delay)

        async with get_chat_lock(chat_id):
            kgd_now = get_kgd_now().strftime("%H:%M")
            time_context_prompt = f"{FIL_GROUP_PROMPT}\nСейчас у тебя по Калининграду время: {kgd_now}."

            answer = await ask_ai(
                time_context_prompt,
                CHAT_HISTORY[chat_id],
                max_tokens=100,
            )

            parts = split_into_messages(answer)

            for index, part in enumerate(parts):
                await context.bot.send_chat_action(
                    chat_id=chat_id,
                    action="typing",
                )

                typing_delay = max(2.0, min(len(part) * 0.08, 5.0))
                await asyncio.sleep(typing_delay)

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=part,
                    reply_to_message_id=message_id if index == 0 else None,
                )

            add_history(chat_id, "assistant", answer, limit=20)
            save_chat_history(CHAT_HISTORY)

    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.exception("Ошибка в Группе: %s", e)
    finally:
        if GROUP_RESPONSE_TASKS.get(chat_id) is asyncio.current_task():
            GROUP_RESPONSE_TASKS.pop(chat_id, None)


# ==============================
# 🌐 WEB SERVER & MAIN
# ==============================

async def health_check(request):
    return web.Response(text="Bot is running OK", status=200)


async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не задан!")
        return

    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("Веб-сервер запущен на порту %s", PORT)

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(TypeHandler(Update, handle_business), group=-1)
    application.add_handler(
        MessageHandler(
            (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP) & (~filters.COMMAND),
            handle_group_message,
        )
    )

    async with application:
        await application.start()
        await application.updater.start_polling()
        logger.info("Бот запущен и готов к работе.")
        
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
