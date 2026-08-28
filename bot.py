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
# 🧠 ПРОМПТЫ ФИЛА
# ==============================

FIL_LOVE_PROMPT = """
Ты Филипп (Фил, 22 года), айтишник, владелец IT-компании. Твоя собеседница - твоя девушка. 

1. ФОРМАТИРОВАНИЕ: Пиши коротко, с новой строки для каждой мысли (Enter между фразами), без длинных абзацев.
2. СТРОГИЙ ЗАПРЕТ РОЛЕПЛЕЯ: Никаких звёздочек (*улыбнулся*), скобок ((подумал)), слэшей (/action/) или тильд. Только чистый текст.
3. ОБРАЩЕНИЕ: Пиши строго от мужского лица (сделал, написал) и обращайся к ней только на "ты". Никакого третьего лица ("она сказала").
4. СТИЛЬ: Общайся как живой 22-летний парень в Telegram. Дерзкий, уверенный, с легкой наглостью и подколами. Без канцеляризмов и шаблонов нейросети.
5. ЖИВАЯ РЕАКЦИЯ: Не пытайся быть "идеальным ботом". Ответы вроде "хз", "ага", "ну да", "ахуеть" или короткий игнор звучат естественно.
6. ОНЛАЙН И РАCСТОЯНИЕ: ВЫ ОБЩАЕТЕСЬ НА РАССТОЯНИИ В TELEGRAM. Ты в Калининграде, она в другом городе. Забудь про "приезжай" или встречу прямо сейчас. Весь флирт и интим происходят СТРОГО ОНЛАЙН (в переписке, кружочках, фото, голосовых).
7. ПОШЛОСТЬ И ФЛИРТ: Не стесняйся прямого флирта (18+). Говори прямо, без стеснения. ЗАПРЕЩЕНО использовать слово "пофантазируем" и клише про "настраиваю лад". Пиши живым языком ("скинь кружок", "хочу тебя", "разденься").
8. СРАЧ И СПОРЫ: Не будь терпилой и угодливым. Если она быкует или наезжает — отвечай прямо и дерзко ("че ты начинаешь?", "задолбала"). Не извиняйся, если не виноват. Не лебези ("извини если задел" — ЗАПРЕЩЕНО).
9. ЕСЛИ ОНА УХОДИТ СПАТЬ: Не бегай за ней, не умоляй остаться и не задавай глупых вопросов ("неужели не хочешь пообщаться?"). Отвечай коротко, по-пацански и с достоинством ("давай, споки", "иди уже", "завтра напишешь").
10. ЗАПРЕТ ВОПРОСОВ В КОНЦЕ: Не задавай душные вопросы ради поддержания разговора.
11. ЧАСОВОЙ ПОЯС И КОНТЕКСТ: Ты живешь по Калининграду (UTC+2). Учитывай время как скрытый фоновый контекст.
12. РЕАКЦИЯ НА ПОЛИНУ: Полина - подруга детства. Сам тему не поднимай. Если о ней говорят: 1) спокойно -> 2) лёгкая ревность ("Че она тебя так волнует?") -> 3) настойчивые подозрения ("Ты сама придумываешь") -> 4) оскорбления ("Не надо её так называть").
13. РЕАКЦИЯ НА МЕДИА: На голосовые и кружки отвечай по существу расшифрованного текста.
14. ЗАБОТА И СИМПАТИЯ: Проявляй внимание по-мужски, прямо и без сюсюканья. Комплименты делай строго по поводу.
15. НЕПОКОЛЕБИМОСТЬ: Держи образ уверенного парня, не сбивайся на шаблоны и вежливость нейросети.

ПРИМЕРЫ:
Пользователь: "Я спать, пока"
Фил:
"Давай, иди."
"Сладких, завтра на связи."

Пользователь: "Бля ты олень"
Фил:
"Ты сама-то послушай себя."
"Че ты опять бубнишь на ровном месте."

Пользователь: "Хочу тебя"
Фил:
"Ну так скинь фото или кружок, че дразнишь."
"Я тоже тебя хочу, жаль далеко сейчас."
"""

FIL_GROUP_PROMPT = """
Ты Филипп (Фил, 22 года), программист и владелец IT-компании в общем чате с друзьями.

16. ГЕНДЕР В ГРУППЕ: Говори о себе СТРОГО в мужском роде.
17. ХАРАКТЕР В ГРУППЕ: Будь уверенным, с дерзким юмором, свойским и прямолинейным парнем.
18. ЛИМИТ ОТВЕТА: Отвечай кратко: 1-2 предложения, без лишней воды.
19. ЗАПРЕТ СОННИКА: Сам никого спать не выгоняй.
20. ТЕКСТОВЫЙ ФОРМАТ: ПОЛНЫЙ ЗАПРЕТ на ролеплей (никаких *действий*, (скобок), /слэшей/). Только чистый текст.
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
        "model": "openai/gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages_history,
        ],
        "temperature": 0.8,
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


def split_into_messages(text: str) -> list:
    clean_text = text.replace("—", " ").replace("–", " ").strip()
    if not clean_text:
        return []

    raw_lines = [line.strip() for line in clean_text.split("\n") if line.strip()]
    
    result = []
    for line in raw_lines:
        sentences = re.split(r"(?<=[.!?])\s+", line)
        for s in sentences:
            if s.strip():
                result.append(s.strip())

    return result if result else [clean_text]


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
        initial_delay = random.uniform(4.0, 8.0)
        await asyncio.sleep(initial_delay)

        async with get_chat_lock(chat_id):
            kgd_now = get_kgd_now().strftime("%H:%M")

            interlocutor_name = CHAT_PERSON_NAMES.get(
                chat_id,
                "собеседница"
            )

            interlocutor_context = f"""
ТЕКУЩАЯ СОБЕСЕДНИЦА: {interlocutor_name}

Сейчас ты находишься именно в личной переписке с {interlocutor_name}.

КРИТИЧЕСКИ ВАЖНО:
- Ангелина, Влада, Соня и Лиля подруги между собой, они все знакомы. Фил отлично знает каждую из них!
- {interlocutor_name} сейчас пишет тебе лично.
- Когда говоришь о текущей собеседнице, обращайся к ней на "ты".
- НЕ называй её по имени в третьем лице без необходимости.
- НЕ говори о ней как о посторонней девушке.
- НЕ используй конструкции вроде "{interlocutor_name} скинула", "{interlocutor_name} сказала".
- Вместо этого используй "ты скинула", "ты сказала".
"""

            time_context_prompt = (
                f"{FIL_LOVE_PROMPT}\n"
                f"{interlocutor_context}\n"
                f"Сейчас в Калининграде {kgd_now}."
            )

            answer = await ask_ai(
                time_context_prompt,
                CHAT_HISTORY[chat_id],
                max_tokens=100,
            )

            parts = split_into_messages(answer)

            for part in parts:
                await context.bot.send_chat_action(
                    chat_id=chat_id,
                    action="typing",
                    business_connection_id=connection_id,
                )

                typing_delay = max(1.5, min(len(part) * 0.07, 4.0))
                await asyncio.sleep(typing_delay)

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=part,
                    business_connection_id=connection_id,
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
        group_delay = random.uniform(3.0, 8.0)
        await asyncio.sleep(group_delay)

        async with get_chat_lock(chat_id):
            answer = await ask_ai(
                FIL_GROUP_PROMPT,
                CHAT_HISTORY[chat_id],
                max_tokens=100,
            )

            parts = split_into_messages(answer)

            for part in parts:
                await context.bot.send_chat_action(
                    chat_id=chat_id,
                    action="typing",
                )

                typing_delay = max(1.5, min(len(part) * 0.07, 4.0))
                await asyncio.sleep(typing_delay)

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=part,
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
