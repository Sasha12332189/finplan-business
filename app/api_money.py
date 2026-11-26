"""Stage 2 API: reports and files, the subscription, invoices and debts."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import documents, finance, plans, reports, runtime, services
from .api import need
from .auth import Ctx, get_ctx
from .models import Counterparty, Debt, Invoice, Report
from .services import owned, q2

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- reports

def resolve_range(business, period: str, start: date | None, end: date | None) -> tuple[date, date]:
    today = finance.local_today(business.timezone)
    if period == "custom":
        if not start or not end or end < start:
            raise HTTPException(422, "Give start and end dates")
        return start, end
    if period.startswith("prev_"):
        return finance.period_range(period[5:], today, -1)
    try:
        return finance.period_range(period, today)
    except ValueError as error:
        raise HTTPException(422, "Unknown period") from error


@router.get("/reports")
async def report(period: str = "month", start: date | None = None, end: date | None = None,
                 ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "read")
    s, e = resolve_range(business, period, start, end)
    plans.check_history(business, s, finance.local_today(business.timezone))
    data = await reports.report_data(ctx.session, business, s, e)
    try:
        plans.check_history(business, data["previous_start"], finance.local_today(business.timezone))
    except HTTPException:
        data["previous"], data["change"] = None, {}
    return data


class SendReport(BaseModel):
    kind: Literal["excel", "pdf", "csv"]
    period: str = "month"
    start: date | None = None
    end: date | None = None


async def build_and_send(session, business, chat_id: int, lang: str, kind: str, start: date, end: date,
                         insight: str | None = None, caption: str | None = None) -> None:
    data = await reports.report_data(session, business, start, end, with_operations=True)
    if kind == "excel":
        content, ext = reports.excel_bytes(business, data, lang, insight), "xlsx"
    elif kind == "pdf":
        content, ext = reports.pdf_bytes(business, data, lang, insight), "pdf"
    else:
        content, ext = reports.csv_bytes(data, lang), "csv"
    file_id = await documents.send_file(chat_id, content, reports.file_name(business, start, end, ext),
                                        caption=caption or f"{business.name} · {start:%d.%m.%Y} – {end:%d.%m.%Y}")
    session.add(Report(business_id=business.id, kind=kind, period=f"{start}..{end}", telegram_file_id=file_id))


@router.post("/reports/send")
async def send_report(body: SendReport, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "export")
    if body.kind != "csv":  # your own records as CSV are always free
        plans.require_feature(business, "reports")
    s, e = resolve_range(business, body.period, body.start, body.end)
    if body.kind != "csv":
        plans.check_history(business, s, finance.local_today(business.timezone))
    try:
        await build_and_send(ctx.session, business, ctx.user.telegram_id, ctx.user.language, body.kind, s, e)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(502, "Could not send the file to the bot chat. Open the bot and press Start, then try again.") from error
    await ctx.session.commit()
    return {"ok": True}


# ---------------------------------------------------------------- subscription

@router.get("/plan")
async def plan(ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = ctx.need_business()
    return plans.status(business)


class PlanInvoice(BaseModel):
    plan: Literal["pro", "team"]
    period: Literal["month", "year"] = "month"


@router.post("/plan/invoice")
async def plan_invoice(body: PlanInvoice, ctx: Ctx = Depends(get_ctx)) -> dict:
    """A Telegram Stars invoice link for Telegram.WebApp.openInvoice()."""
    business, _ = need(ctx, "billing")
    bot = runtime.require_bot()
    title, description = plans.TITLES[body.plan]
    stars = plans.price_of(body.plan, body.period)
    extra = {"subscription_period": plans.SUBSCRIPTION_PERIOD} if body.period == "month" else {}
    label = title + (" · 30 днів" if body.period == "month" else " · 365 днів")
    link = await bot.create_invoice_link(title=label[:32], description=description[:255],
                                         payload=plans.invoice_payload(body.plan, body.period, business.id, ctx.user.telegram_id),
                                         currency="XTR", prices=[LabeledPrice(label=label[:32], amount=stars)], **extra)
    return {"link": link, "stars": stars}


async def set_auto_renew(ctx: Ctx, canceled: bool) -> dict:
    business, _ = need(ctx, "billing")
    if not business.plan_charge_id or business.plan_period != "month":
        raise HTTPException(409, "There is no active Telegram Stars subscription")
    bot = runtime.require_bot()
    try:
        await bot.edit_user_star_subscription(user_id=ctx.user.telegram_id,
                                              telegram_payment_charge_id=business.plan_charge_id, is_canceled=canceled)
    except Exception as error:
        raise HTTPException(503, "Telegram could not change the subscription. If it was paid by another member, "
                                 "they need to do it. Try again later.") from error
    business.plan_canceled = canceled
    await ctx.session.commit()
    return plans.status(business)


@router.post("/plan/cancel")
async def plan_cancel(ctx: Ctx = Depends(get_ctx)) -> dict:
    """Stop auto-renewal; the plan stays active until the paid period ends."""
    return await set_auto_renew(ctx, True)


@router.post("/plan/resume")
async def plan_resume(ctx: Ctx = Depends(get_ctx)) -> dict:
    return await set_auto_renew(ctx, False)


# ---------------------------------------------------------------- invoices

class InvoiceItem(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    qty: Decimal = Field(gt=0)
    price: Decimal = Field(ge=0)


class InvoiceIn(BaseModel):
    counterparty_id: int | None = None
    items: list[InvoiceItem] = Field(min_length=1, max_length=50)
    due_date: date | None = None
    note: str | None = Field(default=None, max_length=1000)
    currency: str | None = None


@router.get("/invoices")
async def invoices(status: str | None = None, ctx: Ctx = Depends(get_ctx)) -> list[dict]:
    business, _ = need(ctx, "read")
    q = select(Invoice).where(Invoice.business_id == business.id)
    if status:
        q = q.where(Invoice.status == status)
    rows = (await ctx.session.scalars(q.order_by(Invoice.number.desc()).limit(200))).all()
    names = await services.counterparty_names(ctx.session, business.id)
    today = finance.local_today(business.timezone)
    return [documents.invoice_dict(i, names, today) for i in rows]


@router.post("/invoices")
async def add_invoice(body: InvoiceIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "write")
    inv = await documents.create_invoice(ctx.session, business, counterparty_id=body.counterparty_id,
                                         items=[i.model_dump(mode="json") for i in body.items], due_date=body.due_date,
                                         note=body.note, currency=body.currency)
    await ctx.session.commit()
    return documents.invoice_dict(inv, await services.counterparty_names(ctx.session, business.id))


@router.patch("/invoices/{inv_id}")
async def edit_invoice(inv_id: int, body: InvoiceIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "write")
    inv = await owned(ctx.session, Invoice, business.id, inv_id, required=True)
    if inv.status == "paid":
        raise HTTPException(409, "A paid invoice cannot change")
    await owned(ctx.session, Counterparty, business.id, body.counterparty_id)
    items = documents.parse_items([i.model_dump(mode="json") for i in body.items])
    import json
    inv.items, inv.total = json.dumps(items, ensure_ascii=False), documents.invoice_total(items)
    inv.counterparty_id, inv.due_date, inv.note = body.counterparty_id, body.due_date or inv.due_date, body.note
    await ctx.session.commit()
    return documents.invoice_dict(inv, await services.counterparty_names(ctx.session, business.id))


class InvoiceAction(BaseModel):
    account_id: int | None = None


@router.post("/invoices/{inv_id}/{action}")
async def invoice_action(inv_id: int, action: Literal["send", "paid", "cancel", "pdf", "remind"],
                         body: InvoiceAction | None = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, member = need(ctx, "write")
    inv = await owned(ctx.session, Invoice, business.id, inv_id, required=True)
    client = await ctx.session.get(Counterparty, inv.counterparty_id) if inv.counterparty_id else None
    lang = ctx.user.language
    if action == "paid":
        await documents.mark_paid(ctx.session, business, member, inv, body.account_id if body else None)
    elif action == "cancel":
        if inv.status == "paid":
            raise HTTPException(409, "A paid invoice cannot be cancelled")
        inv.status = "cancelled"
    elif action in ("send", "pdf", "remind"):
        if inv.status in ("cancelled",):
            raise HTTPException(409, "The invoice is cancelled")
        if action in ("pdf", "remind"):
            plans.require_feature(business, "invoice_pdf")
        text = documents.reminder_text(business, inv, client.name if client else None, lang) if action == "remind" else \
            (f"Рахунок №{inv.number} · {finance.money(inv.total, inv.currency)}" if lang != "ru" else
             f"Счёт №{inv.number} · {finance.money(inv.total, inv.currency)}")
        buttons = [[InlineKeyboardButton(text="Переслать клиенту" if lang == "ru" else "Переслати клієнту",
                                         url=documents.share_url(text))]]
        if client and client.telegram_username:
            buttons.append([InlineKeyboardButton(text=f"@{client.telegram_username}", url=f"https://t.me/{client.telegram_username}")])
        markup = InlineKeyboardMarkup(inline_keyboard=buttons)
        try:
            if plans.limits_for(business)["invoice_pdf"] and action != "remind":
                pdf = documents.invoice_pdf(business, inv, client, lang)
                await documents.send_file(ctx.user.telegram_id, pdf, f"invoice_{inv.number}.pdf", caption=text, reply_markup=markup)
            else:
                await runtime.require_bot().send_message(ctx.user.telegram_id, text, reply_markup=markup)
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(502, "Could not send to the bot chat. Open the bot, press Start and try again.") from error
        if action == "send" and inv.status == "draft":
            inv.status = "sent"
    await ctx.session.commit()
    return documents.invoice_dict(inv, await services.counterparty_names(ctx.session, business.id),
                                  finance.local_today(business.timezone))


@router.delete("/invoices/{inv_id}")
async def delete_invoice(inv_id: int, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "write")
    inv = await owned(ctx.session, Invoice, business.id, inv_id, required=True)
    if inv.status == "paid":
        raise HTTPException(409, "A paid invoice cannot be deleted; cancel the payment operation first")
    await ctx.session.delete(inv)
    await ctx.session.commit()
    return {"ok": True}


# ---------------------------------------------------------------- debts

class DebtIn(BaseModel):
    counterparty_id: int | None = None
    direction: Literal["they_owe", "we_owe"] = "they_owe"
    amount: Decimal = Field(gt=0)
    due_date: date | None = None
    note: str | None = Field(default=None, max_length=500)


@router.get("/debts")
async def debts(ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "read")
    rows = (await ctx.session.scalars(select(Debt).where(Debt.business_id == business.id)
                                      .order_by(Debt.status, Debt.due_date))).all()
    names = await services.counterparty_names(ctx.session, business.id)
    items = [documents.debt_dict(d, names) for d in rows]
    open_ = [d for d in rows if d.status == "open"]
    return {"items": items,
            "they_owe": q2(sum((Decimal(d.amount) for d in open_ if d.direction == "they_owe"), Decimal(0))),
            "we_owe": q2(sum((Decimal(d.amount) for d in open_ if d.direction == "we_owe"), Decimal(0)))}


async def add_debt_row(session, business, body: dict) -> Debt:
    await owned(session, Counterparty, business.id, body.get("counterparty_id"))
    d = Debt(business_id=business.id, **body)
    session.add(d)
    await session.flush()
    return d


@router.post("/debts")
async def add_debt(body: DebtIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "write")
    d = await add_debt_row(ctx.session, business, body.model_dump())
    await ctx.session.commit()
    return documents.debt_dict(d, await services.counterparty_names(ctx.session, business.id))


@router.patch("/debts/{debt_id}")
async def edit_debt(debt_id: int, body: DebtIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "write")
    d = await owned(ctx.session, Debt, business.id, debt_id, required=True)
    await owned(ctx.session, Counterparty, business.id, body.counterparty_id)
    for k, v in body.model_dump().items():
        setattr(d, k, v)
    await ctx.session.commit()
    return documents.debt_dict(d, await services.counterparty_names(ctx.session, business.id))


class DebtClose(BaseModel):
    record_operation: bool = True
    account_id: int | None = None


@router.post("/debts/{debt_id}/close")
async def close_debt(debt_id: int, body: DebtClose, ctx: Ctx = Depends(get_ctx)) -> dict:
    """Mark a debt as settled; optionally record the money as an income/expense operation."""
    business, member = need(ctx, "write")
    d = await owned(ctx.session, Debt, business.id, debt_id, required=True)
    if d.status == "closed":
        raise HTTPException(409, "Already closed")
    d.status = "closed"
    if body.record_operation:
        kind = "income" if d.direction == "they_owe" else "expense"
        cat = await services.resolve_category(ctx.session, business.id, kind, None, d.note or "")
        await services.record_operation(ctx.session, business, member, kind=kind, amount=d.amount, account_id=body.account_id,
                                        category_id=cat.id if cat else None, counterparty_id=d.counterparty_id,
                                        note=d.note or ("Повернення боргу" if ctx.user.language != "ru" else "Возврат долга"))
    await ctx.session.commit()
    return documents.debt_dict(d, await services.counterparty_names(ctx.session, business.id))


@router.delete("/debts/{debt_id}")
async def delete_debt(debt_id: int, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "write")
    d = await owned(ctx.session, Debt, business.id, debt_id, required=True)
    await ctx.session.delete(d)
    await ctx.session.commit()
    return {"ok": True}
