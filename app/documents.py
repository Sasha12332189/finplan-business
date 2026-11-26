"""Invoices to clients (with a PDF), debts, and the delivery of files to the bot chat."""
from __future__ import annotations

import io
import json
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import quote

from aiogram.types import BufferedInputFile
from fastapi import HTTPException
from sqlalchemy import func, select

from . import finance, plans, runtime, services
from .finance import q2
from .models import Business, Category, Counterparty, Debt, Invoice, Member, Operation, utcnow
from .reports import _wrap, pdf_fonts


def parse_items(raw) -> list[dict]:
    items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    out = []
    for it in items:
        name = str(it.get("name") or "").strip()[:200]
        qty = Decimal(str(it.get("qty") or 1))
        price = Decimal(str(it.get("price") or 0))
        if not name or qty <= 0 or price < 0:
            raise HTTPException(422, "Each item needs a name, a positive quantity and a price")
        out.append({"name": name, "qty": float(qty), "price": float(q2(price)), "sum": float(q2(qty * price))})
    if not out:
        raise HTTPException(422, "An invoice needs at least one item")
    return out


def invoice_total(items: list[dict]) -> Decimal:
    return q2(sum(Decimal(str(i["sum"])) for i in items))


async def invoices_this_month(session, business: Business) -> int:
    today = finance.local_today(business.timezone)
    start = date(today.year, today.month, 1)
    return int(await session.scalar(select(func.count()).select_from(Invoice).where(
        Invoice.business_id == business.id, Invoice.created_at >= start)) or 0)


async def create_invoice(session, business: Business, *, counterparty_id: int | None, items, due_date: date | None,
                         note: str | None = None, currency: str | None = None) -> Invoice:
    plans.check_count(business, "invoices_per_month", await invoices_this_month(session, business))
    await services.owned(session, Counterparty, business.id, counterparty_id)
    parsed = parse_items(items)
    business.invoice_counter = (business.invoice_counter or 0) + 1
    inv = Invoice(business_id=business.id, number=business.invoice_counter, counterparty_id=counterparty_id,
                  items=json.dumps(parsed, ensure_ascii=False), total=invoice_total(parsed),
                  currency=(currency or business.currency).upper(), status="draft",
                  due_date=due_date or finance.local_today(business.timezone) + timedelta(days=7), note=note)
    session.add(inv)
    await session.flush()
    return inv


async def mark_paid(session, business: Business, member: Member | None, inv: Invoice, account_id: int | None = None) -> Operation:
    if inv.status == "paid":
        raise HTTPException(409, "Invoice is already paid")
    cat = await services.resolve_category(session, business.id, "income", "services", "")
    op = await services.record_operation(session, business, member, kind="income", amount=inv.total, currency=inv.currency,
                                         category_id=cat.id if cat else None, counterparty_id=inv.counterparty_id,
                                         account_id=account_id, note=f"Рахунок №{inv.number}", source="app")
    inv.status, inv.paid_operation_id = "paid", op.id
    return op


def invoice_dict(inv: Invoice, names: dict[int, str] | None = None, today: date | None = None) -> dict:
    status = inv.status
    if status == "sent" and inv.due_date and today and inv.due_date < today:
        status = "overdue"
    return {"id": inv.id, "number": inv.number, "counterparty_id": inv.counterparty_id,
            "counterparty": (names or {}).get(inv.counterparty_id), "items": [{**i, "sum": i.get("sum", float(i["qty"]) * float(i["price"]))} for i in json.loads(inv.items or "[]")],
            "total": q2(inv.total), "currency": inv.currency, "status": status, "due_date": inv.due_date,
            "note": inv.note, "paid_operation_id": inv.paid_operation_id, "created_at": inv.created_at}


def debt_dict(d: Debt, names: dict[int, str] | None = None) -> dict:
    return {"id": d.id, "counterparty_id": d.counterparty_id, "counterparty": (names or {}).get(d.counterparty_id),
            "direction": d.direction, "amount": q2(d.amount), "due_date": d.due_date, "status": d.status, "note": d.note}


# ---------------------------------------------------------------- invoice PDF

PDF_WORDS = {
    "ru": {"invoice": "Счёт", "from": "Поставщик", "to": "Плательщик", "date": "Дата", "due": "Оплатить до",
           "item": "Наименование", "qty": "Кол-во", "price": "Цена", "sum": "Сумма", "total": "Итого к оплате",
           "no_vat": "Без НДС"},
    "uk": {"invoice": "Рахунок", "from": "Постачальник", "to": "Платник", "date": "Дата", "due": "Сплатити до",
           "item": "Найменування", "qty": "К-сть", "price": "Ціна", "sum": "Сума", "total": "Разом до сплати",
           "no_vat": "Без ПДВ"},
}


def invoice_pdf(business: Business, inv: Invoice, client: Counterparty | None, lang: str) -> bytes:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    w = PDF_WORDS["ru" if lang == "ru" else "uk"]
    font, bold = pdf_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    M = 48
    ink, muted, line_c, primary = HexColor("#1C2620"), HexColor("#6A766E"), HexColor("#DCE2DC"), HexColor("#3A5242")
    money = lambda v: finance.money(v, inv.currency).replace(" ", " ")  # noqa: E731
    c.setTitle(f"{w['invoice']} {inv.number}")
    c.setFillColor(primary)
    c.circle(M + 10, H - 60, 10, stroke=0, fill=1)
    c.setFillColor(HexColor("#546E5C"))
    c.circle(M + 22, H - 60, 10, stroke=0, fill=1)
    c.setFillColor(ink)
    c.setFont(bold, 22)
    c.drawString(M + 44, H - 68, f"{w['invoice']} № {inv.number}")
    c.setFont(font, 10)
    c.setFillColor(muted)
    c.drawString(M, H - 100, f"{w['date']}: {inv.created_at:%d.%m.%Y}")
    if inv.due_date:
        c.drawString(M + 160, H - 100, f"{w['due']}: {inv.due_date:%d.%m.%Y}")
    y = H - 140
    for label, lines in ((w["from"], [business.name]), (w["to"], [client.name if client else "—"] +
                                                         ([client.tax_id] if client and client.tax_id else []) +
                                                         ([client.phone] if client and client.phone else []))):
        c.setFillColor(muted)
        c.setFont(font, 9)
        c.drawString(M, y, label)
        c.setFillColor(ink)
        c.setFont(bold, 11)
        for k, ln in enumerate(lines):
            c.drawString(M + 110, y - k * 14, str(ln))
            c.setFont(font, 10)
        y -= 18 + 14 * len(lines)
    y -= 10
    cols = [M, M + 280, M + 340, M + 420]
    c.setFillColor(primary)
    c.rect(M, y - 6, W - 2 * M, 22, stroke=0, fill=1)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont(bold, 9.5)
    for x, label, right in ((cols[0] + 8, w["item"], False), (cols[2] - 8, w["qty"], True),
                            (cols[3] - 8, w["price"], True), (W - M - 8, w["sum"], True)):
        (c.drawRightString if right else c.drawString)(x, y + 1, label)
    y -= 24
    c.setFont(font, 10)
    for i, it in enumerate(json.loads(inv.items or "[]")):
        if i % 2:
            c.setFillColor(HexColor("#F4F5F1"))
            c.rect(M, y - 6, W - 2 * M, 20, stroke=0, fill=1)
        c.setFillColor(ink)
        c.drawString(cols[0] + 8, y, _wrap(c, it["name"], font, 10, 260)[0] if it["name"] else "")
        c.drawRightString(cols[2] - 8, y, f"{it['qty']:g}")
        c.drawRightString(cols[3] - 8, y, money(it["price"]))
        c.drawRightString(W - M - 8, y, money(it.get("sum", float(it["qty"]) * float(it["price"]))))
        y -= 20
    c.setStrokeColor(line_c)
    c.line(M, y + 8, W - M, y + 8)
    c.setFont(bold, 13)
    c.drawRightString(W - M - 8, y - 14, f"{w['total']}: {money(inv.total)}")
    c.setFont(font, 9)
    c.setFillColor(muted)
    if not business.is_vat_payer:
        c.drawRightString(W - M - 8, y - 30, w["no_vat"])
    if inv.note:
        for k, ln in enumerate(_wrap(c, inv.note, font, 9.5, W - 2 * M)[:6]):
            c.drawString(M, y - 60 - k * 13, ln)
    c.drawString(M, 40, "finplan Business")
    c.showPage()
    c.save()
    return buf.getvalue()


def reminder_text(business: Business, inv: Invoice, client_name: str | None, lang: str) -> str:
    money = finance.money(inv.total, inv.currency).replace(" ", " ")
    if lang == "ru":
        return (f"Здравствуйте{', ' + client_name if client_name else ''}! Напоминаем об оплате счёта №{inv.number} "
                f"на {money}{' до ' + inv.due_date.strftime('%d.%m.%Y') if inv.due_date else ''}. Спасибо! — {business.name}")
    return (f"Добрий день{', ' + client_name if client_name else ''}! Нагадуємо про оплату рахунку №{inv.number} "
            f"на {money}{' до ' + inv.due_date.strftime('%d.%m.%Y') if inv.due_date else ''}. Дякуємо! — {business.name}")


def share_url(text: str) -> str:
    return "https://t.me/share/url?url=%20&text=" + quote(text)


async def send_file(chat_id: int, content: bytes, filename: str, caption: str | None = None, reply_markup=None) -> str | None:
    """Send a file to a chat; returns Telegram's file_id (kept in Report as a cache key)."""
    bot = runtime.require_bot()
    msg = await bot.send_document(chat_id, BufferedInputFile(content, filename=filename), caption=caption,
                                  reply_markup=reply_markup)
    return msg.document.file_id if msg.document else None


__all__ = ["create_invoice", "mark_paid", "invoice_pdf", "invoice_dict", "debt_dict", "send_file", "utcnow",
           "Category"]
