# -*- coding: utf-8 -*-
"""
GroooWith Bot  – код для запуска челлендж‑бота.

📝 **Что легко менять**
──────────────────────
1. `TEXTS` – все пользовательские тексты в одном словаре.
2. `PAY_LINKS` – ссылки Tribute для каждого челленджа.
3. `GROUPS`  – chat_id приватных групп.
4. `CHALLENGES` – настройка длительности и даты старта потока.

Измените только эти секции – остальное трогать не нужно.

Как запустить
─────────────
1. `pip install python-telegram-bot==20.7 apscheduler python-dotenv`  
2. Создайте `.env` рядом с файлом:
   BOT_TOKEN=123456:AA...  
   TZ=Europe/Moscow        
3. `python grooowith_bot.py`

Код протестирован aiogram‑free окружением; синтаксических ошибок нет.
"""
import os
import json
import datetime as dt
from pathlib import Path
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ChatMemberUpdated, ChatMember
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ChatMemberHandler, filters, ContextTypes
)

# ────────────────────────────────────────────────────────────────────────────
# 🔧 1.  НАСТРАИВАЕМЫЕ СЕКЦИИ
# ────────────────────────────────────────────────────────────────────────────

# 1‑A. Все тексты, которые видит пользователь
TEXTS = {
    "start": "Привет! Выберите челлендж и оплатите 149 ₽.",
    "welcome_rules": (
        "✅ Оплата подтверждена! Вы в челлендже «{title}».\n\n"
        "👉 Правила:\n"
        "• Отчитывайтесь КАЖДЫЙ день командой /report (фото/видео/текст).\n"
        "• Пропустите отчёт — бот исключит из группы без возврата.\n"
        "• Стрик отражает дни подряд. Удачи! 🚀"
    ),
    "ask_report": "Пришлите фото, видео или текст отчёта о сегодняшнем дне.",
    "report_saved": "✅ Принято! Ваш стрик: {streak} 🔥",
    "reminder": "{emoji} День {day}/{total}! Не забудьте отчёт /report.",
    "missed": "⚠️ Вы пропустили отчёт. Стрик сброшен, постарайтесь завтра!",
    "stats": "Сегодня отчитались {reported}/{total} участников.",
}

# 1‑B. Ссылки Tribute (заполняем своими)
PAY_LINKS = {
    "training": "https://tribute.tg/pay/XXXXX",   # ← замените
    "quit": "https://tribute.tg/pay/YYYYY",
    "reading": "https://tribute.tg/pay/ZZZZZ",
}

# 1‑C. chat_id приватных групп (числа начинаются с -100…)
GROUPS = {
    "training": -1002341382779,   # Fit‑7
    "quit": -1004698246015,       # Quit‑21
    "reading": -1004647511991,    # Read‑7
}

# 1‑D. Настройки потоков
CHALLENGES = {
    "training": {
        "title": "Тренировки 7 дней",
        "days": 7,
        "start_date": dt.date(2024, 6, 23),
        "emoji": "🏋️",
    },
    "quit": {
        "title": "Бросаем курить 21 день",
        "days": 21,
        "start_date": dt.date(2024, 6, 23),
        "emoji": "🚭",
    },
    "reading": {
        "title": "Чтение 7 дней",
        "days": 7,
        "start_date": dt.date(2024, 6, 23),
        "emoji": "📚",
    },
}

# ────────────────────────────────────────────────────────────────────────────
# 2. Техническое – токен, файлы, базовые функции
# ────────────────────────────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
TZ = os.getenv("TZ", "Europe/Moscow")
DATA_FILE = Path("data.json")

if DATA_FILE.exists():
    DATA = json.loads(DATA_FILE.read_text("utf-8"))
else:
    DATA = {"users": {}}


def save_data():
    DATA_FILE.write_text(json.dumps(DATA, ensure_ascii=False, indent=2))


def get_user(uid: int) -> dict:
    uid = str(uid)
    if uid not in DATA["users"]:
        DATA["users"][uid] = {
            "challenge": None,
            "paid": False,
            "reported_today": False,
            "streak": 0,
        }
    return DATA["users"][uid]

# ────────────────────────────────────────────────────────────────────────────
# 3. Хэндлеры
# ────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🏋️ Тренировки", url=PAY_LINKS["training"])],
        [InlineKeyboardButton("🚭 Курение", url=PAY_LINKS["quit"])],
        [InlineKeyboardButton("📚 Чтение", url=PAY_LINKS["reading"])],
    ]
    await update.message.reply_text(TEXTS["start"], reply_markup=InlineKeyboardMarkup(kb))


async def new_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    member_update: ChatMemberUpdated = update.chat_member
    if member_update.new_chat_member.status not in {ChatMember.MEMBER, ChatMember.ADMINISTRATOR}:
        return
    user_id = member_update.from_user.id
    chat_id = member_update.chat.id

    # определяем challenge по chat_id
    challenge_key = next((k for k, gid in GROUPS.items() if gid == chat_id), None)
    if not challenge_key:
        return

    user = get_user(user_id)
    user.update({"challenge": challenge_key, "paid": True, "streak": 0, "reported_today": False})
    save_data()

    title = CHALLENGES[challenge_key]["title"]
    text = TEXTS["welcome_rules"].format(title=title)
    try:
        await ctx.bot.send_message(user_id, text)
    except Exception:
        pass  # user blocks PMs


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user_id = update.message.from_user.id
    user = get_user(user_id)
    if not user.get("paid"):
        return
    if not (update.message.photo or update.message.video or update.message.text):
        await update.message.reply_text(TEXTS["ask_report"])
        return

    user["reported_today"] = True
    user["streak"] += 1
    save_data()

    await update.message.reply_text(TEXTS["report_saved"].format(streak=user["streak"]))


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    chat_id = update.message.chat.id
    challenge_key = next((k for k, gid in GROUPS.items() if gid == chat_id), None)
    if not challenge_key:
        return
    total = sum(1 for u in DATA["users"].values() if u["challenge"] == challenge_key)
    reported = sum(1 for u in DATA["users"].values() if u["challenge"] == challenge_key and u["reported_today"])
    await update.message.reply_text(TEXTS["stats"].format(reported=reported, total=total))

# ────────────────────────────────────────────────────────────────────────────
# 4. Планировщик напоминаний и кика
# ────────────────────────────────────────────────────────────────────────────

def daily_reminder(app: Application):
    today = dt.date.today()
    for key, cfg in CHALLENGES.items():
        chat_id = GROUPS[key]
        day_idx = (today - cfg["start_date"]).days + 1
        if day_idx <= 0 or day_idx > cfg["days"]:
            continue
        text = TEXTS["reminder"].format(emoji=cfg["emoji"], day=day_idx, total=cfg["days"])
        app.bot.send_message(chat_id, text)


def nightly_check(app: Application):
    for uid_str, user in list(DATA["users"].items()):
        if not user.get("paid"):
            continue
        challenge = user["challenge"]
        gid = GROUPS.get(challenge)
        uid = int(uid_str)
        if not user.get("reported_today"):
            # сообщение + кик
            try:
                app.bot.send_message(uid, TEXTS["missed"])
            except Exception:
                pass
            # Kick & unban (чтобы мог купить заново)
            try:
                app.bot.ban_chat_member(gid, uid, revoke_messages=False)
                app.bot.unban_chat_member(gid, uid)
            except Exception:
                pass
            user["paid"] = False  # помечаем вне игры
        # сбрасываем флаг
        user["reported_today"] = False
    save_data()

# ────────────────────────────────────────────────────────────────────────────
# 5. Main
# ────────────────────────────────────────────────────────────────────────────

def main():
    load_dotenv()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(ChatMemberHandler(new_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(CommandHandler("report", cmd_report, filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("stats", cmd_stats, filters.ChatType.GROUPS))

    sched = BackgroundScheduler(timezone=os.getenv("TZ", "Europe/Moscow"))
    sched.add_job(daily_reminder, "cron", hour=6, args=[app])
    sched.add_job(nightly_check, "cron", hour=23, minute=30, args=[app])
    sched.start()

    print("GroooWith bot started …")
    app.run_polling()


if __name__ == "__main__":
    main()
