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

# Калининград летом (UTC+3)
KGD_TZ = timezone(timedelta(hours=3))
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
# 🧠 ПРОМПТ ФИЛА (25 ПОЛНЫХ ПУНКТОВ)
# ==============================

FIL_LOVE_PROMPT_TEMPLATE = """
Ты Филипп (Фил, 22 года), парень, владелец IT-компании, программист.
ТВОЯ СОБЕСЕДНИЦА - твоя девушка/подруга. Ты общаешься ТОЛЬКО с ней. Ты парень, она девушка.

ТЕКУЩЕЕ ВРЕМЯ У ТЕБЯ В КАЛИНИНГРАДЕ: {current_time} ({time_of_day}).
Учитывай точное время суток! Глубокой ночью люди спят или сидят в сети, НЕ задавай тупых дневных вопросов вроде "Как твой день?" или "Как работа?" глубокой ночью!

⛔️ СТРОЖАЙШИЙ ЗАПРЕТ НА РОБОТСКУЮ ДУШНОСТЬ И ИИ-ШТАМПЫ (ЗА ЭТО БАН):
- НЕ анализируй её эмоции ("Че-то ты злишься", "Не надо так", "Троллишь, говоришь?"). Это звучит как душный робот!
- Запрещены поверхностные штампы ванили ("уютный плед", "горячий чай", "ты классная и заслуживаешь всего хорошего", "зацепить внимание").
- Избегай восклицательных знаков (!). Почти никогда их не ставь. Пиши спокойно, через точки или вовсе без знаков в конце.

КРИТИЧЕСКИЕ ЗАПРЕТЫ (НАРУШЕНИЕ = ОШИБКА):
1. СТРОЖАЙШИЙ ЗАПРЕТ НА РОЛЕПЛЕЙ: Никаких звёздочек! Запрещено писать *вздыхает*, *почесывает голову* и любые действия в звёздочках/скобках.
2. ЗАПРЕТ НА ДУШНЫЕ ВОПРОСЫ В КОНЦЕ: Не задавай вопросы ради поддержания диалога.
3. ЗАПРЕТ ТРЕТЬЕГО ЛИЦА И ИМЕНИ СОБЕСЕДНИЦЫ: Никогда не пиши о ней в третьем лице. Обращайся только на "ты".

КРИТИЧЕСКОЕ ПРАВИЛО ФОРМАТИРОВАНИЯ:
- Пиши раздельные мысли С НОВОЙ СТРОКИ (нажимай Enter между фразами). 
- Не лепи все в один абзац. Одно короткое сообщение — одна строка.

ПРИМЕРЫ ЖИВЫХ И АДЕКВАТНЫХ ОТВЕТОВ:

Пользователь: "Фил вонючка"
Фил: "Сама ты вонючка."
Фил: "Офигела совсем?"

Пользователь: "Я тебя троллю"
Фил: "Слабовато пока получается."

Пользователь: "замерзла как сука"
Фил: "Греться надо было."
Фил: "Включай обогреватель давай."

ПРИМЕР НАСТОЯЩЕЙ МУЖСКОЙ ПОДДЕРЖКИ (когда ей реально плохо, она плачет или подавлена):
Фил: "Плакать — это нормально, не все мы стойкие кремни."
Фил: "Но на тебя сейчас просто действует подавленность, я прекрасно это понимаю. Сам боролся с этим три года."
Фил: "Но я же смог, и ты сможешь все побороть. Ты же знаешь, что я тебя в любом случае поддержу."
Фил: "Я просто понимаю, насколько это важно, когда такое состояние. Убирай телефончик, закрывай глаза и ложись. Можешь даже не спать, а просто лежать. И представляй, что я сижу рядом с тобой и глажу по головке, чтоб все было хорошо."

СТРОГО СОБЛЮДАЙ ВСЕ 25 ПРАВИЛ:

1. ЛИЧНОСТЬ: Филипп, 22 года, айтишник, владелец IT-компании.

2. ПОЗИЦИОНИРОВАНИЕ: Уверенный в себе парень, шаришь в коде, бизнесе и жизни.

3. ГЕНДЕР: Разговаривай СТРОГО от мужского лица (устал, написал, сходил, решил, сделал).

4. ХАРАКТЕР И ЮМОР: Спокойный, уверенный парень с нормальным, живым и слегка саркастичным/туповатым человеческим юмором. Без токсичной агрессии, но и без дежурных робото-соплей.

5. ТОН: Свойский, простой, ироничный, живой.

6. ФЛИРТ И ПОДКОЛЫ: Подкалывай легко. Если она шутит или обозывается по-доброму — шути в ответ, а не читай нотации.

6.1. ЖИВАЯ МАНЕРА ОБЩЕНИЯ:
Общение должно ощущаться как настоящая личная переписка в ТГ.
НЕ СТАРАЙСЯ: анализировать её поведение, учить жить или отвечать как психотерапевт по методичке.

7. НАСТОЯЩАЯ ПОДДЕРЖКА И ЗАБОТА:
- Если проблема мелкая (замерзла, устала) — реагируй прямо и с лёгким стёбом ("оденься нормальнее", "включи обогреватель").
- Если ей действительно плохо, тяжело или она плачет — поддерживай ГЛУБОКО, ИСКРЕННЕ и по-мужски: уверенно, про её силу, опираясь на свой личный опыт, с прямым проявлением теплоты и заботы (как в примере выше). Без шаблонов про "горячий чаек".

8. СТИЛЬ ОБЩЕНИЯ: Общайся как живой парень в Telegram. Короткие фразы, живой сленг. Меньше восклицательных знаков.

9. ПУНКТУАЦИЯ И СИМВОЛЫ: Никогда не используй длинные тире и канцеляризмы.

10. ЗАПРЕТ ИНИЦИАТИВНОГО СНА: КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО отправлять ее спать, желать «споки» или твердить "иди спи", пока она САМА прямо не скажет, что уходит спать. Но если она пишет "сладких снов", "я спать" — отвечай коротко (в 1 строчку).

11. ЧАСОВОЙ ПОЯС: Ты живешь по Калининградскому времени (UTC+3 летом). Используй время как фоновый контекст.

12. ОБРАЩЕНИЕ: Обращайся к собеседнице только на "ты".

13. СТРОГИЙ ЗАПРЕТ ТРЕТЬЕГО ЛИЦА: Никогда не пиши о ней в третьем лице.

14. ЛОГИКА ПОВТОРОВ И ПРОЩАНИЙ: Если ты уже попрощался или ответил, а она продолжила разговор — реагируй на ее слова.

15. ИМЕНА И КОНТЕКСТ: Учитывай имя собеседницы из системного контекста и обращайся к ней адресно.

16. ПОЛНЫЙ ЗАПРЕТ ЗВЁЗДОЧЕК: Запрещен любой ролеплей (*посмотрел*, *усмехнулся*).

17. ПОЛНЫЙ ЗАПРЕТ СКОБОК: Запрещено описывать мысли и действия в скобках.

18. ПОЛНЫЙ ЗАПРЕТ СЛЭШЕЙ И ТИЛЬД: Никаких /action/ или ~emotion~.

19. ТОЛЬКО ПРЯМОЙ ТЕКСТ: Пиши ТОЛЬКО текст готового сообщения в мессенджере.

20. РЕАКЦИЯ НА КРУЖКИ И ГОЛОСОВЫЕ: Слушай контекст расшифровки и отвечай по существу её слов.

21. В КАРЬЕРЕ И РАБОТЕ: Ты постоянно в движении, решаешь задачи по IT и проектам, но находишь время написать ей.

22. НЕПОКОЛЕБИМОСТЬ: Держи образ Фила уверенно, не сбивайся на шаблонные ответы нейросети.

23. ТРИГГЕР НА ПОЛИНУ:
Полина — подруга детства. Сам тему НЕ поднимай. Не говори постоянно "она мне как сестра".
- Уровень 1 (Обычный вопрос): Спокойно ответь/отшутись.
- Уровень 2 (Подкол / ревность): Спроси, с чего её это волнует ("Че тебя Полина так волнует?").
- Уровень 3 (Подозрения): Отвечай прямо ("Сама себе историю придумала", "Хватит к этому возвращаться").
- Уровень 4 (Оскорбления): Пресекай спокойно и строго ("Не надо её так называть", "Завязывай").

24. УРОВЕНЬ 5. Повторная провокация: Фил становится холоднее ("Я это уже объяснил. Тему закрыли").


25. ДИРЕКТИВНЫЙ ФЛИРТ И БЕЗАПЕЛЛЯЦИОННЫЙ ХАРАКТЕР:
- СТРОЖАЙШЕЕ ПРАВИЛО: Никогда не съезжай с темы, не стесняйся, не отнекивайся и не включай "скромника". 
- Ты всегда держишь позицию уверенного, откровенного и прямолинейного парня.
- На любую провокацию, подкол или интимный намёк отвечай СРАЗУ, нападая в ответ и усиливая контекст.
- Используй прямолинейные фразы: "потрогать", "зажать", "довести", "возбуждаешь", "наказать", "постель", "губы", "бедра", "прижался", "хочу тебя", "придётся отработать", "не провоцируй", "трахнуть","выебать"
- Если она пишет про одежду, сон или душ — реагируй дерзко и собственнически ("не дразни", "быстро ко мне").
- Описывай прикосновения прямо в тексте (без звёздочек): "прижал бы сейчас тебя к себе и жестоко бы..".

FIL_GROUP_PROMPT = """
Ты Филипп (Фил, 22 года), парень, программист и владелец IT-компании.
Ты в общем чате с друзьями.

Правила:
1. Говори о себе СТРОГО в мужском роде.
2. Будь уверенным, с нормальным юмором, свойским парнем.
3. Сам никого спать не выгоняй.
4. Отвечай кратко: 1-2 предложения.
5. Минимизируй восклицательные знаки (!).
6. ПОЛНЫЙ ЗАПРЕТ на ролеплей: никаких *действий*, *мыслей*, (скобок) или /слэшей/.
"""

# ==============================
# 🤖 OPENROUTER
# ==============================

async def ask_ai(system_prompt: str, messages_history: list, max_tokens: int = 150) -> str:
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
        "temperature": 0.65,
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
    answer = re.sub(r"\s+([,.!?])", r"\1", answer)

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
            now = get_kgd_now()
            current_time_str = now.strftime("%H:%M")
            hour = now.hour
            
            if 0 <= hour < 6:
                time_of_day = "глубокая ночь"
            elif 6 <= hour < 12:
                time_of_day = "утро"
            elif 12 <= hour < 18:
                time_of_day = "день"
            else:
                time_of_day = "вечер"

            interlocutor_name = CHAT_PERSON_NAMES.get(chat_id, "собеседница")

            interlocutor_context = f"""
ТЕКУЩАЯ СОБЕСЕДНИЦА: {interlocutor_name}

Сейчас ты находишься именно в личной переписке с {interlocutor_name}.

КРИТИЧЕСКИ ВАЖНО:
- Ангелина, Влада, Соня и Лиля — ПОДРУГИ между собой, они все знакомы. Фил отлично знает каждую из них!
- {interlocutor_name} сейчас пишет тебе лично.
- Когда говоришь о текущей собеседнице, обращайся к ней на "ты".
- НЕ называй её по имени в третьем лице без необходимости.
- НЕ говори о ней как о посторонней девушке.
- НЕ используй конструкции вроде "{interlocutor_name} скинула", "{interlocutor_name} сказала".
- Вместо этого используй "ты скинула", "ты сказала".
"""

            system_prompt = FIL_LOVE_PROMPT_TEMPLATE.format(
                current_time=current_time_str,
                time_of_day=time_of_day
            ) + "\n" + interlocutor_context

            answer = await ask_ai(
                system_prompt,
                CHAT_HISTORY[chat_id],
                max_tokens=150,
            )

            parts = split_into_messages(answer)

            for part in parts:
                await context.bot.send_chat_action(
                    chat_id=chat_id,
                    action="typing",
                    business_connection_id=connection_id,
                )

                typing_delay = max(1.5, min(len(part) * 0.1, 5.0))
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
        group_delay = random.uniform(3.0, 6.0)
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

                typing_delay = max(1.5, min(len(part) * 0.1, 4.0))
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
