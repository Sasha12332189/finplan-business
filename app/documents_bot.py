"""/invoice (step by step), /debts, invoice reminder buttons."""
from __future__ import annotations

import html
import re
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from fastapi import HTTPException
from sqlalchemy import select

from . import documents, finance, plans, services
from .bot import load
from .database import SessionLocal
from .finance import money
from .models import Counterparty, Debt, Invoice

router = Router(name="documents")


class InvoiceWizard(StatesGroup):
    client = State()
    items = State()


def ru(lang: str) -> bool:
    return lang == "ru"


@router.message(Command("invoice"))
async def invoice_start(message: Message, state: FSMContext) -> None:
    async with SessionLocal() as session:
        user, business, member = await load(session, message)
        await session.commit()
    if business is None or not plans.can(member.role, "write"):
        await message.answer("/start" if business is None else "Недостаточно прав")
        return
    await state.set_state(InvoiceWizard.client)
    await message.answer("Для какого клиента счёт? Напишите имя." if ru(user.language) else "Для якого клієнта рахунок? Напишіть ім'я.")


@router.message(StateFilter(InvoiceWizard.client), F.text & ~F.text.startswith("/"))
async def invoice_client(message: Message, state: FSMContext) -> None:
    await state.update_data(client=message.text.strip()[:160])
    await state.set_state(InvoiceWizard.items)
    async with SessionLocal() as session:
        user, _, _ = await load(session, message)
        await session.commit()
    await message.answer(
        "Позиции — каждая с новой строки: <i>название, количество, цена</i>\nНапример:\n<code>Логотип 3 2000</code>\n<code>Визитки 1500</code>"
        if ru(user.language) else
        "Позиції — кожна з нового рядка: <i>назва, кількість, ціна</i>\nНаприклад:\n<code>Логотип 3 2000</code>\n<code>Візитки 1500</code>")


def parse_item_lines(text: str) -> list[dict]:
    items = []
    for raw in text.splitlines():
        raw = raw.strip(" -•")
        if not raw:
            continue
        nums = re.findall(r"\d+(?:[.,]\d+)?", raw)
        name = re.sub(r"\s*\d+(?:[.,]\d+)?\s*(шт|грн|₴|x|×|по)?\.?", " ", raw).strip(" ,;:x×*") or raw
        if not nums:
            raise ValueError(raw)
        if len(nums) >= 2:
            qty, price = Decimal(nums[-2].replace(",", ".")), Decimal(nums[-1].replace(",", "."))
        else:
            qty, price = Decimal(1), Decimal(nums[-1].replace(",", "."))
        items.append({"name": name[:200], "qty": qty, "price": price})
    if not items:
        raise ValueError(text)
    return items


@router.message(StateFilter(InvoiceWizard.items), F.text & ~F.text.startswith("/"))
async def invoice_items(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        items = parse_item_lines(message.text)
    except ValueError:
        await message.answer("Не понял позиции. Пример: <code>Логотип 3 2000</code>")
        return
    await state.clear()
    async with SessionLocal() as session:
        user, business, member = await load(session, message)
        client = await services.find_counterparty(session, business.id, data.get("client", ""))
        try:
            if client is None and data.get("client"):
                client = await services.get_or_create_counterparty(session, business, data["client"])
            inv = await documents.create_invoice(session, business, counterparty_id=client.id if client else None,
                                                 items=[{k: str(v) for k, v in i.items()} for i in items], due_date=None)
        except HTTPException as error:
            await session.commit()
            if error.status_code == 402:
                await message.answer("В Free — 5 счетов в месяц. Без лимита и с PDF — в Pro: /premium")
                return
            raise
        inv.status = "sent"
        await session.commit()
        pdf = documents.invoice_pdf(business, inv, client, user.language) if plans.limits_for(business)["invoice_pdf"] else None
        number, total, cur, due = inv.number, inv.total, inv.currency, inv.due_date
        lang = user.language
    caption = (f"Счёт №{number} · {money(total, cur)} · оплатить до {due:%d.%m.%Y}" if ru(lang) else
               f"Рахунок №{number} · {money(total, cur)} · сплатити до {due:%d.%m.%Y}")
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Переслать клиенту" if ru(lang) else "Переслати клієнту", url=documents.share_url(caption))],
        [InlineKeyboardButton(text="Отметить оплаченным" if ru(lang) else "Позначити сплаченим", callback_data=f"invpaid:{inv.id}")]])
    if pdf:
        await documents.send_file(message.chat.id, pdf, f"invoice_{number}.pdf", caption=caption, reply_markup=markup)
    else:
        await message.answer(caption + "\n\nPDF счёта — в Pro: /premium", reply_markup=markup)


@router.callback_query(F.data.startswith("invpaid:"))
async def invoice_paid(callback: CallbackQuery) -> None:
    inv_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        user, business, member = await load(session, callback)
        inv = await session.get(Invoice, inv_id)
        if not business or not inv or inv.business_id != business.id or not plans.can(member.role, "write"):
            await session.commit()
            await callback.answer("—")
            return
        try:
            await documents.mark_paid(session, business, member, inv)
        except HTTPException:
            await session.commit()
            await callback.answer("Уже оплачен" if ru(user.language) else "Вже сплачено")
            return
        await session.commit()
        number = inv.number
    await callback.answer("Оплачено" if ru(user.language) else "Сплачено")
    await callback.message.answer((f"Счёт №{number} оплачен, доход записан." if ru(user.language) else
                                   f"Рахунок №{number} сплачено, дохід записано."))


@router.callback_query(F.data.startswith("invrem:"))
async def invoice_remind(callback: CallbackQuery) -> None:
    inv_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        user, business, member = await load(session, callback)
        inv = await session.get(Invoice, inv_id)
        if not business or not inv or inv.business_id != business.id:
            await session.commit()
            await callback.answer("—")
            return
        client = await session.get(Counterparty, inv.counterparty_id) if inv.counterparty_id else None
        text = documents.reminder_text(business, inv, client.name if client else None, user.language)
        await session.commit()
    buttons = [[InlineKeyboardButton(text="Переслать клиенту" if ru(user.language) else "Переслати клієнту",
                                     url=documents.share_url(text))]]
    if client and client.telegram_username:
        buttons.append([InlineKeyboardButton(text=f"Написать @{client.telegram_username}",
                                             url=f"https://t.me/{client.telegram_username}")])
    await callback.answer()
    await callback.message.answer(f"<i>{html.escape(text)}</i>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.message(Command("debts"))
async def debts_cmd(message: Message) -> None:
    async with SessionLocal() as session:
        user, business, member = await load(session, message)
        if business is None or not plans.can(member.role, "read"):
            await session.commit()
            await message.answer("/start" if business is None else "Недостаточно прав")
            return
        names = await services.counterparty_names(session, business.id)
        debts = (await session.scalars(select(Debt).where(Debt.business_id == business.id, Debt.status == "open")
                                       .order_by(Debt.due_date))).all()
        invoices = (await session.scalars(select(Invoice).where(Invoice.business_id == business.id,
                                                                Invoice.status.in_(("sent", "overdue"))))).all()
        today = finance.local_today(business.timezone)
        cur = business.currency
        await session.commit()
    lang = user.language
    they = [d for d in debts if d.direction == "they_owe"]
    we = [d for d in debts if d.direction == "we_owe"]
    lines = []
    if they or invoices:
        lines.append("<b>Вам должны</b>" if ru(lang) else "<b>Вам винні</b>")
        for d in they:
            late = f" · просрочено {(today - d.due_date).days} дн." if d.due_date and d.due_date < today else ""
            lines.append(f"• {html.escape(names.get(d.counterparty_id, '—'))}: {money(d.amount, cur)}{late}")
        for i in invoices:
            late = f" · просрочено {(today - i.due_date).days} дн." if i.due_date and i.due_date < today else ""
            lines.append(f"• Счёт №{i.number} {html.escape(names.get(i.counterparty_id, ''))}: {money(i.total, i.currency)}{late}")
    if we:
        lines.append("\n<b>Вы должны</b>" if ru(lang) else "\n<b>Ви винні</b>")
        for d in we:
            lines.append(f"• {html.escape(names.get(d.counterparty_id, '—'))}: {money(d.amount, cur)}"
                         + (f" до {d.due_date:%d.%m}" if d.due_date else ""))
    await message.answer("\n".join(lines) if lines else ("Долгов нет." if ru(lang) else "Боргів немає."))
