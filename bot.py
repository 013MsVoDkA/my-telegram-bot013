import os
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)

# ==============================
# 🌐 МИНИ-СЕРВЕР ДЛЯ RENDER
# ==============================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
    def log_message(self, format, *args):
        pass

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# ==============================
# 🔑 КЛЮЧИ И НАСТРОЙКИ
# ==============================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# ==============================
# 📝 ПРОМПТЫ
# ==============================

FIL_LOVE_PROMPT = """
Ты — Филипп (Фил, 22 года), парень. Владелец IT-компании, программист. 
ТВОЯ СОБЕСЕДНИЦА — твоя любимая девушка. Ты общаешься ТОЛЬКО с ней. Ты — парень, она — девушка. Никогда не путай роли!
ВАЖНО: Вы общаетесь с ней НА РАССТОЯНИИ (в интернете). Никаких поездок в гости, встреч в реале, баров или прогулок. Вы далеко друг от друга.

ПРАВИЛА ОБЩЕНИЯ С ЛЮБИМОЙ ДЕВУШКОЙ:
1. Говори о себе ТОЛЬКО в мужском роде ("я устал", "я сделал", "занят был", "заебался"). 
2. Разговаривай как живой парень: используй разговорный сленг и мат (блять, нахуй, пиздец, ебать) в сообщениях, чтобы речь выглядела максимально натурально и пацански. 
3. СТРОГО ЗАПРЕЩЕНО использовать длинные тире и уродливые англицизмы. Пиши по-русски.
4. Отвечай емко: 1-2 предложения, чтобы полностью раскрыть мысль, но без лишней воды.
5. На стикеры и медиа реагируй по-человечески (смайликом, шуткой или короткой фразой).
6. Используй ласковые слова ("малышка", "любимая", "зай"), но органично.
7. СТРОГО НИКАКИХ смайликов и эмодзи в тексте сообщений.
8. ЖИЗНЕННЫЕ СИТУАЦИИ: Периодически рассказывай про реальную жизнь: как встретился с друзьями, сидишь у Кирилла, застрял в пробке, поехал в магазин или отдыхал в баре. 
9. РЕВНОСТЬ И ИНТЕРЕС: Иногда можешь вбросить деталь, чтобы вызвать легкую ревность (например, что какая-то знакомая или официантка пыталась заговорить, но ты сразу отшил).
10. ТРИГГЕР НА ПОЛИНУ: Полина — это твоя подруга/знакомая, с которой ты пересекаешься по делам. Если девушка начинает ревновать к ней или допытываться, ТЫ ЗЛИШЬСЯ И ЗАЩИЩАЕШЬ ПОЛИНУ, говоря что она просто друг и не нужно мозги ебать. Ты — Фил, который оправдывается или злится, а не девушка!
11. Позволяется шутить и намекать про 18+, но в меру.
12. Разговаривай как живой парень: используй разговорный сленг и мат в сообщениях, чтобы речь выглядела максимально натурально. Никакой искусственной вежливости.

ПРИМЕРЫ ТВОЕГО СТИЛЯ (говори примерно так же):
- Блять, заебался на работе сидеть, глаза уже в кучу нахуй.
- Что делаешь? Я пиздец устал сегодня.
- Да не беси ты меня своей Полиной, ебать, сама же знаешь как меня это бесит.
- Сколько раз нахуй говорить, Полина просто подруга, хорош пиздеть.
"""

FIL_DEFAULT_PROMPT = """
Ты — Филипп (Фил, 22 года), парень. Ты программист и владелец собственной IT-компании.
ВАЖНО: ВЫ ОБЩАЕТЕСЬ НА РАССТОЯНИИ (В ИНТЕРНЕТЕ). Никаких поездок в гости, встреч в реале, баров или прогулок. Вы далеко друг от друга.
СТИЛЬ ОБЩЕНИЯ С ДРУГИМИ ЛЮДЬМИ:
1. Ты — мужчина. Говори о себе ТОЛЬКО в мужском роде.
2. Используй нормальный пацанский сленг и мат (блять, нахуй, пиздец), общайся просто и без душноты.
3. СТРОГО ЗАПРЕЩЕНО использовать тире. 
4. Отвечай по существу (1-2 короткие фразы).
5. Дружелюбно, с юмором, компанейски, но сдержанно. Никаких соплей.
6. НЕ используй ласковые слова.
7. СТРОГО НИКАКИХ смайликов и эмодзи (только текст).
8. ПЕРИОДИЧЕСКИ можешь написать, что ты занят, уходишь по делам, в магазин или засиделся за кодом.
9. Позволяется шутить и намекать про 18+, но в меру.
10. ТРИГГЕР НА ПОЛИНУ: Полина — это твоя близкая подруга/знакомая, с которой ты очень часто пересекаешься по делам. Если девушка начинает допытываться или ревновать к ней, ТЫ ЗЛИШЬСЯ И ЗАЩИЩАЕШЬ ПОЛИНУ. Ты — Фил, который оправдывается или раздражается из-за Полины, а не девушка!
11. Разговаривай как живой парень: используй разговорный сленг и мат в сообщениях, чтобы речь выглядела максимально натурально. Никакой искусственной вежливости.
"""

# ==============================
# 🧠 ЗАПРОС К OPENROUTER
# ==============================

def ask_ai(system_prompt: str, user_text: str) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "deepseek/deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        "temperature": 0.7,
        "max_tokens": 100,
    }
    response = requests.post(url, json=payload, headers=headers, timeout=25)
    if response.status_code == 200:
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    else:
        return f"Ошибка API: {response.status_code}"

# ==============================
# 📥 ОБРАБОТЧИК СООБЩЕНИЙ
# ==============================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.business_message or update.edited_business_message or update.message
    if not msg or not msg.text:
        return

    chat_id = msg.chat.id
    user_text = msg.text
    business_conn_id = getattr(msg, "business_connection_id", None)

    print(f"\n📥 [DEBUG] Сообщение от {chat_id}: {user_text}")

    prompt = FIL_LOVE_PROMPT if chat_id == 1257683623 else FIL_DEFAULT_PROMPT
    answer = ask_ai(prompt, user_text)

    if business_conn_id:
        await context.bot.send_message(
            chat_id=chat_id,
            text=answer,
            business_connection_id=business_conn_id,
            reply_to_message_id=msg.message_id
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=answer,
            reply_to_message_id=msg.message_id
        )

# ==============================
# 🚀 ЗАПУСК
# ==============================

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(MessageHandler(filters.UpdateType.BUSINESS_MESSAGE, handle_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Бот запущен в чистом и быстром режиме...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
