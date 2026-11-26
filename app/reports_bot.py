"""/report: pick a period and a format, get the file in the chat."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from fastapi import HTTPException

from . import finance, plans
from .api_money import build_and_send
from .bot import load
from .database import SessionLocal

router = Router(name="reports")

PERIODS = {"ru": [("month", "Этот месяц"), ("prev_month", "Прошлый месяц"), ("quarter", "Квартал"),
                  ("prev_quarter", "Прошлый квартал"), ("year", "Год")],
           "uk": [("month", "Цей місяць"), ("prev_month", "Минулий місяць"), ("quarter", "Квартал"),
                  ("prev_quarter", "Минулий квартал"), ("year", "Рік")]}


def lang_key(lang: str) -> str:
    return "ru" if lang == "ru" else "uk"


@router.message(Command("report"))
async def report_cmd(message: Message) -> None:
    async with SessionLocal() as session:
        user, business, member = await load(session, message)
        await session.commit()
    if business is None:
        await message.answer("/start")
        return
    lang = lang_key(user.language)
    rows = [[InlineKeyboardButton(text=label, callback_data=f"rp:{key}")] for key, label in PERIODS[lang]]
    await message.answer("За какой период?" if lang == "ru" else "За який період?",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("rp:"))
async def report_period(callback: CallbackQuery) -> None:
    period = callback.data.split(":", 1)[1]
    async with SessionLocal() as session:
        user, business, _ = await load(session, callback)
        await session.commit()
    lang = lang_key(user.language)
    pro = business is not None and plans.limits_for(business)["reports"]
    lock = "" if pro else " 🔒"
    rows = [[InlineKeyboardButton(text="Excel" + lock, callback_data=f"rk:excel:{period}"),
             InlineKeyboardButton(text="PDF" + lock, callback_data=f"rk:pdf:{period}")],
            [InlineKeyboardButton(text="CSV", callback_data=f"rk:csv:{period}")]]
    await callback.answer()
    await callback.message.edit_text("Формат файла:" if lang == "ru" else "Формат файлу:",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("rk:"))
async def report_kind(callback: CallbackQuery) -> None:
    _, kind, period = callback.data.split(":", 2)
    await callback.answer("Готовлю файл…" if True else "")
    async with SessionLocal() as session:
        user, business, member = await load(session, callback)
        lang = user.language
        if business is None or not plans.can(member.role, "export"):
            await session.commit()
            await callback.message.answer("Недостаточно прав" if lang == "ru" else "Недостатньо прав")
            return
        today = finance.local_today(business.timezone)
        offset = -1 if period.startswith("prev_") else 0
        start, end = finance.period_range(period.removeprefix("prev_"), today, offset)
        try:
            if kind != "csv":
                plans.require_feature(business, "reports")
                plans.check_history(business, start, today)
            await build_and_send(session, business, callback.from_user.id, lang, kind, start, end)
            await session.commit()
        except HTTPException as error:
            await session.commit()
            if error.status_code == 402:
                await callback.message.answer("Excel и PDF отчёты — в Pro. Подключить: /premium\nCSV со всеми записями доступен всегда."
                                              if lang == "ru" else
                                              "Excel і PDF звіти — у Pro. Підключити: /premium\nCSV з усіма записами доступний завжди.")
                return
            raise
        except Exception:
            logging.exception("Report failed")
            await callback.message.answer("Не получилось, попробуйте ещё раз.")
