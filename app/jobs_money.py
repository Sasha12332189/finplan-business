"""Stage 2 automatic messages: the weekly report on Monday morning, the monthly report (with Excel
for Pro) on the 1st, overdue invoices with a "remind the client" button."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from . import finance, jobs, plans, services
from .finance import money
from .models import Business, Invoice

# Set by app.ai: async fn(session, business, start, end, lang) -> str | None (one insight sentence)
insight_provider = None


async def insight(session, business: Business, start, end, lang: str) -> str | None:
    if insight_provider is None or not plans.limits_for(business)["ai_requests"]:
        return None
    try:
        return await insight_provider(session, business, start, end, lang)
    except Exception:
        logging.exception("AI insight failed")
        return None


def summary_lines(lang: str, title: str, cur: str, s: finance.Summary, prev: finance.Summary) -> str:
    def ch(a, b):
        p = finance.pct_change(a, b)
        return f" ({'+' if p and p > 0 else ''}{p}%)" if p is not None else ""
    if lang == "ru":
        return (f"<b>{title}</b>\nВыручка: <b>{money(s.revenue, cur)}</b>{ch(s.revenue, prev.revenue)}\n"
                f"Расходы: <b>{money(s.expenses, cur)}</b>{ch(s.expenses, prev.expenses)}\n"
                f"Прибыль: <b>{money(s.profit, cur)}</b>{ch(s.profit, prev.profit)}")
    return (f"<b>{title}</b>\nВиручка: <b>{money(s.revenue, cur)}</b>{ch(s.revenue, prev.revenue)}\n"
            f"Витрати: <b>{money(s.expenses, cur)}</b>{ch(s.expenses, prev.expenses)}\n"
            f"Прибуток: <b>{money(s.profit, cur)}</b>{ch(s.profit, prev.profit)}")


async def weekly(session, bot, business: Business, lang: str, now: datetime) -> None:
    if not business.weekly_digest or now.weekday() != 0 or now.hour < jobs.WEEKLY_HOUR:
        return
    start, end = finance.period_range("week", now.date(), -1)
    key = f"weekly:{start}"
    if key in services.notices(business):
        return
    s = finance.summarize(await services.load_ops(session, business.id, start, end))
    ps, pe = finance.period_range("week", now.date(), -2)
    prev = finance.summarize(await services.load_ops(session, business.id, ps, pe))
    if s.revenue or s.expenses:
        title = (f"Неделя {start:%d.%m}–{end:%d.%m}" if lang == "ru" else f"Тиждень {start:%d.%m}–{end:%d.%m}")
        text = summary_lines(lang, title, business.currency, s, prev)
        tip = await insight(session, business, start, end, lang)
        if tip:
            text += f"\n\n💡 {tip}"
        await jobs.send(bot, await jobs.recipients(session, business), text)
    services.add_notice(business, key)


async def monthly(session, bot, business: Business, lang: str, now: datetime) -> None:
    if not business.monthly_report or now.day != 1 or now.hour < jobs.MONTHLY_HOUR:
        return
    start, end = finance.period_range("month", now.date(), -1)
    key = f"monthly:{start:%Y-%m}"
    if key in services.notices(business):
        return
    services.add_notice(business, key)
    s = finance.summarize(await services.load_ops(session, business.id, start, end))
    if not (s.revenue or s.expenses):
        return
    ps, pe = finance.period_range("month", now.date(), -2)
    prev = finance.summarize(await services.load_ops(session, business.id, ps, pe))
    title = f"{'Месяц' if lang == 'ru' else 'Місяць'} {start:%m.%Y}"
    text = summary_lines(lang, title, business.currency, s, prev)
    if plans.limits_for(business)["auto_report"]:
        from .api_money import build_and_send
        tip = await insight(session, business, start, end, lang)
        for chat_id in await jobs.recipients(session, business, ("owner", "admin", "accountant")):
            try:
                await build_and_send(session, business, chat_id, lang, "excel", start, end, insight=tip, caption=text[:1000])
            except Exception:
                logging.exception("Monthly report to %s failed", chat_id)
    else:
        # one teaser line, no pop-ups
        text += ("\n\nExcel-отчёт за месяц приходит сюда автоматически в Pro: /premium" if lang == "ru" else
                 "\n\nExcel-звіт за місяць приходить сюди автоматично в Pro: /premium")
        await jobs.send(bot, business.owner_telegram_id, text)


async def overdue_invoices(session, bot, business: Business, lang: str, now: datetime) -> None:
    today = now.date()
    rows = (await session.scalars(select(Invoice).where(
        Invoice.business_id == business.id, Invoice.status.in_(("sent", "overdue")),
        Invoice.due_date.is_not(None), Invoice.due_date < today))).all()
    if not rows:
        return
    names = await services.counterparty_names(session, business.id)
    sent = services.notices(business)
    for inv in rows:
        inv.status = "overdue"
        days = (today - inv.due_date).days
        if days not in (1, 3, 7, 14, 30):
            continue
        key = f"invoice:{inv.id}:{days}"
        if key in sent:
            continue
        who = names.get(inv.counterparty_id, "")
        text = (f"Счёт №{inv.number}{' для ' + who if who else ''} просрочен на {days} дн. · {money(inv.total, inv.currency)}"
                if lang == "ru" else
                f"Рахунок №{inv.number}{' для ' + who if who else ''} прострочено на {days} дн. · {money(inv.total, inv.currency)}")
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Напомнить клиенту" if lang == "ru" else "Нагадати клієнту", callback_data=f"invrem:{inv.id}"),
            InlineKeyboardButton(text="Оплачен" if lang == "ru" else "Сплачено", callback_data=f"invpaid:{inv.id}")]])
        if await jobs.send(bot, await jobs.recipients(session, business), text, reply_markup=markup):
            services.add_notice(business, key)


async def cash_gap_warning(session, bot, business: Business, lang: str, now: datetime) -> None:
    if not plans.limits_for(business)["forecast"] or now.hour < jobs.WEEKLY_HOUR:
        return
    gap = await services.cash_gap(session, business, now.date())
    if not gap or (gap["date"] - now.date()).days > 7:
        return
    key = f"gap:{gap['date']}"
    if key in services.notices(business):
        return
    text = (f"Кассовый разрыв: {gap['date']:%d.%m} {gap['note'] or 'платёж'} {money(gap['amount'], business.currency)}, "
            f"а на счетах будет {money(gap['balance'], business.currency)}." if lang == "ru" else
            f"Касовий розрив: {gap['date']:%d.%m} {gap['note'] or 'платіж'} {money(gap['amount'], business.currency)}, "
            f"а на рахунках буде {money(gap['balance'], business.currency)}.")
    if await jobs.send(bot, await jobs.recipients(session, business), text):
        services.add_notice(business, key)


jobs.EXTRA_JOBS.extend([weekly, monthly, overdue_invoices, cash_gap_warning])
__all__ = ["timedelta"]
