 text = re.sub(
        r"\*[^*]{1,100}\*",
        "",
        text,
    )

    text = re.sub(
        r"/[^/\n]{1,100}/",
        "",
        text,
    )

    # Не даём модели писать по 10 пустых строк
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


# ============================================================
# 🧩 РАЗДЕЛЕНИЕ НА СООБЩЕНИЯ
# ============================================================

def split_into_messages(text: str) -> list:
    """
    Сохраняем переносы, которые сама модель сделала.

    НЕ режем каждое предложение по точке.
    Иначе живое сообщение превращается в 3-4 отдельных сообщения.
    """

    clean_text = clean_ai_answer(text)

    if not clean_text:
        return []

    lines = [
        line.strip()
        for line in clean_text.splitlines()
        if line.strip()
    ]

    # Максимум 4 отдельных сообщения
    lines = lines[:4]

    return lines


# ============================================================
# 🤖 OPENROUTER
# ============================================================

async def ask_ai(
    system_prompt: str,
    messages_history: list,
    max_tokens: int = 70,
) -> str:

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY не задан"
        )

    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "openai/gpt-4o-mini",

        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            *messages_history,
        ],

        "temperature": 0.8,

        "max_tokens": max_tokens,
    }

    async with httpx.AsyncClient(
        timeout=35.0
    ) as client:

        response = await client.post(
            url,
            json=payload,
            headers=headers,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Ошибка OpenRouter "
                f"{response.status_code}: "
                f"{response.text}"
            )

        data = response.json()

    try:
        answer = data["choices"][0]["message"]["content"]

    except (
        KeyError,
        IndexError,
        TypeError,
    ):
        raise RuntimeError(
            f"Неожиданный ответ OpenRouter: {data}"
        )

    answer = clean_ai_answer(str(answer))

    if not answer:
        raise RuntimeError(
            "OpenRouter вернул пустой ответ"
        )

    return answer


async def generate_love_answer(
    system_prompt: str,
    history: list,
) -> str:

    answer = await ask_ai(
        system_prompt,
        history,
        max_tokens=70,
    )

    # Если модель выдала шаблонную фигню,
    # просим её полностью переделать ответ.
    if has_bad_phrase(answer):

        logger.warning(
            "Обнаружен плохой ответ модели: %s",
            answer,
        )

        retry_prompt = system_prompt + """

Предыдущий вариант получился неестественным.

Напиши полностью другой ответ.

Он должен быть коротким и живым.
Не анализируй собеседницу.
Не объясняй очевидное.
Не задавай вопрос без необходимости.
Не используй шаблонные фразы.
"""

        answer = await ask_ai(
            retry_prompt,
            history,
            max_tokens=60,
        )

    return clean_ai_answer(answer)


# ============================================================
# 🎙️ GROQ WHISPER
# ============================================================

async def transcribe_audio(
    file_bytes: bytearray,
    filename: str,
) -> str:

    if not GROQ_API_KEY:
        return "(голосовое/кружок)"

    url = (
        "https://api.groq.com/openai/v1/"
        "audio/transcriptions"
    )

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
    }

    files = {
        "file": (
            filename,
            bytes(file_bytes),
        ),
    }

    data = {
        "model": "whisper-large-v3",
    }

    try:

        async with httpx.AsyncClient(
            timeout=40.0
        ) as client:

            response = await client.post(
                url,
                headers=headers,
                data=data,
                files=files,
            )

        if response.status_code != 200:
            logger.warning(
                "Groq вернул %s: %s",
                response.status_code,
                response.text,
            )

            return "(голосовое/кружок)"

        transcript = (
            response
            .json()
            .get("text", "")
            .strip()
        )

        if transcript:
            return (
                "(голосовое/кружок): "
                f"{transcript}"
            )

        return "(голосовое/кружок)"

    except Exception as e:

        logger.warning(
            "Ошибка распознавания аудио: %s",
            e,
        )

        return "(голосовое/кружок)"


# ============================================================
# 👤 ИМЯ ПОЛЬЗОВАТЕЛЯ
# ============================================================

def get_user_display_name(user) -> str:

    if not user:
        return "Кто-то"

    name = (
        user.first_name or ""
    ).strip()

    if user.last_name:
        name = (
            f"{name} "
            f"{user.last_name}"
        ).strip()

    return (
        name
        or user.username
        or "Кто-то"
    )


# ============================================================
# 💼 BUSINESS ЛИЧКА
# ============================================================

async def handle_business(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.business_message:
        return

    msg = update.business_message

    chat_id = msg.chat.id

    if (
        chat_id not in ALL_CHAT_IDS
        or not msg.business_connection_id
    ):
        return

    user_text = msg.text

    # --------------------------------------------------------
    # 🎙️ Аудио / кружки / медиа
    # --------------------------------------------------------

    if not user_text:

        file_obj = (
            msg.voice
            or msg.video_note
            or msg.audio
            or (
                msg.document
                if (
                    msg.document
                    and msg.document.mime_type
                    and "audio"
                    in msg.document.mime_type
                )
                else None
            )
        )

        if file_obj:

            try:

                telegram_file = (
                    await context.bot.get_file(
                        file_obj.file_id
                    )
                )

                file_bytes = (
                    await telegram_file
                    .download_as_bytearray()
                )

                if (
                    msg.audio
                    and msg.audio.file_name
                ):
                    filename = (
                        msg.audio.file_name
                    )
                else:
                    filename = "audio.ogg"

                user_text = (
                    await transcribe_audio(
                        file_bytes,
                        filename,
                    )
                )

            except Exception as e:

                logger.warning(
                    "Ошибка аудио: %s",
                    e,
                )

                user_text = (
                    "(отправила "
                    "голосовое/кружок)"
                )

        elif msg.sticker:

            user_text = "[Отправила стикер]"

        elif msg.photo:

            user_text = "[Отправила фото]"

        elif msg.video:

            user_text = "[Отправила видео]"

        else:

            user_text = "[Медиа/Файл]"

    # --------------------------------------------------------
    # 🧠 Сохраняем сообщение
    # --------------------------------------------------------

    add_history(
        chat_id,
        "user",
        user_text,
        limit=20,
    )

    logger.info(
        "BUSINESS | chat=%s | %s",
        chat_id,
        user_text[:200],
    )

    # --------------------------------------------------------
    # ❌ Отменяем предыдущий ответ
    # --------------------------------------------------------

    old_task = BUSINESS_RESPONSE_TASKS.get(
        chat_id
    )

    if (
        old_task
        and not old_task.done()
    ):
        old_task.cancel()

    # --------------------------------------------------------
    # 🚀 Создаём новый ответ
    # --------------------------------------------------------

    task = asyncio.create_task(
        process_business_response(
            update,
            context,
            chat_id,
            msg.business_connection_id,
            msg.message_id,
        )
    )

    BUSINESS_RESPONSE_TASKS[chat_id] = task


# ============================================================
# 💬 ГЕНЕРАЦИЯ BUSINESS ОТВЕТА
# ============================================================

async def process_business_response(
    update,
    context,
    chat_id,
    connection_id,
    message_id,
):

    try:

        # Небольшая естественная задержка
        initial_delay = random.uniform(
            2.5,
            5.0,
        )

        await asyncio.sleep(
            initial_delay
        )

        async with get_chat_lock(chat_id):

            now = get_kgd_now()

            current_time_str = (
                now.strftime("%H:%M")
            )

            hour = now.hour

            if 0 <= hour < 6:
                time_of_day = (
                    "глубокая ночь"
                )

            elif 6 <= hour < 12:
                time_of_day = "утро"

            elif 12 <= hour < 18:
                time_of_day = "день"

            else:
                time_of_day = "вечер"

            interlocutor_name = (
                CHAT_PERSON_NAMES.get(
                    chat_id,
                    "собеседница",
                )
            )

            interlocutor_context = f"""
Сейчас ты переписываешься лично с {interlocutor_name}.

Это не группа.

Она пишет тебе лично.

Обращайся к ней на "ты".

Не говори о ней в третьем лице.

Ангелина, Влада, Соня и Лиля знакомы между собой.
Ты знаешь их всех.

Текущая собеседница:
{interlocutor_name}
"""

            system_prompt = (
                FIL_LOVE_PROMPT_TEMPLATE.format(
                    current_time=current_time_str,
                    time_of_day=time_of_day,
                )
                + "\n"
                + interlocutor_context
            )

            # ------------------------------------------------
            # 🤖 Получаем ответ
            # ------------------------------------------------

            answer = await generate_love_answer(
                system_prompt,
                CHAT_HISTORY[chat_id],
            )

            parts = split_into_messages(
                answer
            )

            if not parts:
                return

            # ------------------------------------------------
            # 📤 Отправляем
            # ------------------------------------------------

            for part in parts:

                await context.bot.send_chat_action(
                    chat_id=chat_id,
                    action="typing",
                    business_connection_id=connection_id,
                )

                # Скорость печати
                typing_delay = max(
                    0.7,
                    min(
                        len(part) * 0.045,
                        2.5,
                    ),
                )

                await asyncio.sleep(
                    typing_delay
                )

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=part,
                    business_connection_id=connection_id,
                )

            # ------------------------------------------------
            # 🧠 Сохраняем ОДИН исходный ответ
            # ------------------------------------------------

            add_history(
                chat_id,
                "assistant",
                answer,
                limit=20,
            )

            save_chat_history(
                CHAT_HISTORY
            )

    except asyncio.CancelledError:

        logger.info(
            "Предыдущий Business-ответ отменён | chat=%s",
            chat_id,
        )

        return

    except Exception as e:

        logger.exception(
            "Ошибка в Business-личке: %s",
            e,
        )

    finally:

        if (
            BUSINESS_RESPONSE_TASKS.get(
                chat_id
            )
            is asyncio.current_task()
        ):
            BUSINESS_RESPONSE_TASKS.pop(
                chat_id,
                None,
            )


# ============================================================
# 👥 ГРУППА
# ============================================================

def group_message_is_for_bot(
    msg,
    bot_username: str | None,
    bot_id: int,
) -> bool:

    # Ответ на сообщение Фила
    if (
        msg.reply_to_message
        and msg.reply_to_message.from_user
        and (
            msg.reply_to_message
            .from_user
            .id
            == bot_id
        )
    ):
        return True

    if (
        not bot_username
        or not msg.text
    ):
        return False

    pattern = (
        rf"(?<!\w)"
        rf"@{re.escape(bot_username)}"
        rf"\b"
    )

    return bool(
        re.search(
            pattern,
            msg.text,
            flags=re.IGNORECASE,
        )
    )


def clean_bot_mention(
    text: str,
    bot_username: str | None,
) -> str:

    if not bot_username:
        return text.strip()

    pattern = (
        rf"(?<!\w)"
        rf"@{re.escape(bot_username)}"
        rf"\b"
    )

    cleaned = re.sub(
        pattern,
        "",
        text,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s{2,}",
        " ",
        cleaned,
    )

    return cleaned.strip()


# ============================================================
# 👥 ОБРАБОТКА ГРУППЫ
# ============================================================

async def handle_group_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    msg = update.message

    if (
        not msg
        or not msg.text
    ):
        return

    chat_id = msg.chat.id

    bot_username = (
        context.bot.username
    )

    # Не обращались к Филу
    if not group_message_is_for_bot(
        msg,
        bot_username,
        context.bot.id,
    ):
        return

    clean_text = clean_bot_mention(
        msg.text,
        bot_username,
    )

    if not clean_text:
        clean_text = (
            "[к Филу обратились]"
        )

    user_name = get_user_display_name(
        msg.from_user
    )

    user_text = (
        f"{user_name}: {clean_text}"
    )

    add_history(
        chat_id,
        "user",
        user_text,
        limit=20,
    )

    logger.info(
        "GROUP | chat=%s | %s",
        chat_id,
        user_text[:200],
    )

    # --------------------------------------------------------
    # ❌ Отменяем предыдущую генерацию
    # --------------------------------------------------------

    old_task = GROUP_RESPONSE_TASKS.get(
        chat_id
    )

    if (
        old_task
        and not old_task.done()
    ):
        old_task.cancel()

    # --------------------------------------------------------
    # 🚀 Новый ответ
    # --------------------------------------------------------

    task = asyncio.create_task(
        process_group_response(
            update,
            context,
            chat_id,
            msg.message_id,
        )
    )

    GROUP_RESPONSE_TASKS[chat_id] = task


# ============================================================
# 🤖 ОТВЕТ В ГРУППЕ
# ============================================================

async def process_group_response(
    update,
    context,
    chat_id,
    message_id,
):

    try:

        group_delay = random.uniform(
            1.5,
            4.0,
        )

        await asyncio.sleep(
            group_delay
        )

        async with get_chat_lock(chat_id):

            answer = await ask_ai(
                FIL_GROUP_PROMPT,
                CHAT_HISTORY[chat_id],
                max_tokens=60,
            )

            answer = clean_ai_answer(
                answer
            )

            # Если группа получила шаблонную фигню,
            # делаем ещё одну попытку.
            if has_bad_phrase(answer):

                answer = await ask_ai(
                    FIL_GROUP_PROMPT
                    + """

Предыдущий ответ был слишком шаблонным.
Напиши совершенно другой короткий ответ.
Без анализа и без искусственного вопроса.
""",
                    CHAT_HISTORY[chat_id],
                    max_tokens=50,
                )

                answer = clean_ai_answer(
                    answer
                )

            parts = split_into_messages(
                answer
            )

            if not parts:
                return

            # ------------------------------------------------
            # 📤 Отправка
            # ------------------------------------------------

            for part in parts:

                await context.bot.send_chat_action(
                    chat_id=chat_id,
                    action="typing",
                )

                typing_delay = max(
                    0.7,
                    min(
                        len(part) * 0.04,
                        2.0,
                    ),
                )

                await asyncio.sleep(
                    typing_delay
                )

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=part,
                )

            # ------------------------------------------------
            # 🧠 История
            # ------------------------------------------------

            add_history(
                chat_id,
                "assistant",
                answer,
                limit=20,
            )

            save_chat_history(
                CHAT_HISTORY
            )

    except asyncio.CancelledError:

        logger.info(
            "Предыдущий ответ группы отменён | chat=%s",
            chat_id,
        )

        return

    except Exception as e:

        logger.exception(
            "Ошибка в Группе: %s",
            e,
        )

    finally:

        if (
            GROUP_RESPONSE_TASKS.get(
                chat_id
            )
            is asyncio.current_task()
        ):
            GROUP_RESPONSE_TASKS.pop(
                chat_id,
                None,
            )


# ============================================================
# 🌐 WEB SERVER
# ============================================================

async def health_check(request):
    return web.Response(
        text="Bot is running OK",
        status=200,
    )


# ============================================================
# 🚀 MAIN
# ============================================================

async def main():

    if not TELEGRAM_BOT_TOKEN:

        logger.error(
            "TELEGRAM_BOT_TOKEN не задан!"
        )

        return

    # --------------------------------------------------------
    # 🌐 Web server
    # --------------------------------------------------------

    app = web.Application()

    app.router.add_get(
        "/",
        health_check,
    )

    app.router.add_get(
        "/health",
        health_check,
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT,
    )

    await site.start()

    logger.info(
        "Веб-сервер запущен на порту %s",
        PORT,
    )

    # --------------------------------------------------------
    # 🤖 Telegram
    # --------------------------------------------------------

    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Business сообщения
    application.add_handler(
        TypeHandler(
            Update,
            handle_business,
        ),
        group=-1,
    )

    # Обычная группа
    application.add_handler(
        MessageHandler(
            (
                filters.ChatType.GROUPS
                | filters.ChatType.SUPERGROUP
            )
            & (~filters.COMMAND),
            handle_group_message,
        )
    )

    # --------------------------------------------------------
    # ▶️ Запуск
    # --------------------------------------------------------

    async with application:

        await application.start()

        await application.updater.start_polling()

        logger.info(
            "Бот запущен и готов к работе."
        )

        await asyncio.Event().wait()


# ============================================================
# 🏁 START
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except (
        KeyboardInterrupt,
        SystemExit,
    ):

        logger.info(
            "Бот остановлен."
        )
   
