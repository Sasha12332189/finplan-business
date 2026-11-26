"""Automatic messages and periodic work (spec section 4), run every few minutes by app/main.py.

Each reminder is sent once: its key is stored in Business.notices.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from aiogram import Bot
from sqlalchemy import select

from . import finance, plans, services
from .database import SessionLocal
from .finance import money
from .models import Business, Member, User
from .tax_rates import LIMIT_WARNINGS, REMINDER_DAYS
from .texts import T

DAILY_HOUR = 21
WEEKLY_HOUR = 9
MONTHLY_HOUR = 10

# Extra jobs registered by later modules: async fn(session, bot, business, owner_lang, local_now)
EXTRA_JOBS: list = []


async def owner_language(session, business: Business) -> str:
    user = await session.scalar(select(User).where(User.telegram_id == business.owner_telegram_id))
    return user.language if user else "uk"


async def recipients(session, business: Business, roles=("owner", "admin")) -> list[int]:
    rows = await session.scalars(select(Member.telegram_id).where(Member.business_id == business.id,
                                                                  Member.role.in_(roles)))
    return list(rows.all())


async def send(bot: Bot | None, chat_ids, text: str, **kwargs) -> bool:
    if bot is None:
        return False
    ok = False
    for chat_id in chat_ids if isinstance(chat_ids, (list, tuple, set)) else [chat_ids]:
        try:
            await bot.send_message(chat_id, text, **kwargs)
            ok = True
        except Exception:
            logging.exception("Failed to send a message to %s", chat_id)
    return ok


async def tax_reminders(session, bot, business: Business, lang: str, today: date) -> None:
    overview = await services.tax_overview(session, business, today)
    if not overview["applicable"]:
        return
    sent = services.notices(business)
    for p in overview["upcoming"]:
        if p.get("accruing"):
            continue
        left = (p["due_date"] - today).days
        if left not in REMINDER_DAYS:
            continue
        key = f"tax:{p['what']}:{p['period']}:{left}"
        if key in sent:
            continue
        text = T(lang, "tax_reminder", what=T(lang, f"tax_item_{p['what']}"), period=p["period"],
                 amount=money(p["amount"]), due=f"{p['due_date']:%d.%m}", days=T(lang, f"days_left_{left}"))
        if await send(bot, await recipients(session, business, ("owner", "admin", "accountant")), text):
            services.add_notice(business, key)
    limit = overview["limit"]
    if limit and limit["level"]:
        key = f"limit:{today.year}:{limit['level']}"
        if key not in sent:
            name = "limit_over" if limit["level"] >= 100 else "limit_warn"
            text = T(lang, name, percent=limit["percent"], group=business.fop_group, used=money(limit["used"]),
                     limit=money(limit["limit"]))
            if await send(bot, await recipients(session, business), text):
                for level in LIMIT_WARNINGS:
                    if level <= limit["level"]:
                        services.add_notice(business, f"limit:{today.year}:{level}")


async def daily_digest(session, bot, business: Business, lang: str, now: datetime) -> None:
    if not business.daily_digest or now.hour < DAILY_HOUR:
        return
    key = f"daily:{now.date()}"
    if key in services.notices(business):
        return
    s = finance.summarize(await services.load_ops(session, business.id, now.date(), now.date()))
    if s.revenue or s.expenses:
        await send(bot, business.owner_telegram_id, T(lang, "daily", revenue=money(s.revenue, business.currency, True),
                                                      expenses=money(-s.expenses, business.currency, True)))
    services.add_notice(business, key)


async def run_once(bot: Bot | None, now_utc: datetime | None = None) -> None:
    async with SessionLocal() as session:
        ids = list((await session.scalars(select(Business.id).order_by(Business.id))).all())
    for business_id in ids:
        # One session per business: a failure in one never touches the others.
        async with SessionLocal() as session:
            try:
                business = await session.get(Business, business_id)
                now = (now_utc.astimezone(finance.ZoneInfo(business.timezone)) if now_utc
                       else finance.local_now(business.timezone))
                today = now.date()
                await services.apply_due_recurring(session, business, today)
                lang = await owner_language(session, business)
                await tax_reminders(session, bot, business, lang, today)
                await daily_digest(session, bot, business, lang, now)
                for job in EXTRA_JOBS:
                    await job(session, bot, business, lang, now)
                await session.commit()
            except Exception:
                await session.rollback()
                logging.exception("Background job failed for business %s", business_id)


__all__ = ["run_once", "EXTRA_JOBS", "send", "recipients", "timedelta", "plans"]
