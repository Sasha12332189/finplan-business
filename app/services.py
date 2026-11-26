"""Database-level operations shared by the bot, the Mini App API, the AI tools and background jobs."""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import finance, fx, plans
from .config import get_settings
from .finance import Op, TaxProfile, ZERO, q2
from .models import (
    Account, Business, Category, Counterparty, Debt, Invoice, Member, Operation, Product, Project,
    RecurringOperation, TaxPeriod, User, utcnow,
)

# key, kind, is_cogs, names
DEFAULT_CATEGORIES = [
    ("sales", "income", False, {"ru": "Продажи", "uk": "Продажі", "en": "Sales"}),
    ("services", "income", False, {"ru": "Услуги", "uk": "Послуги", "en": "Services"}),
    ("prepayment", "income", False, {"ru": "Предоплата", "uk": "Передоплата", "en": "Prepayment"}),
    ("other_income", "income", False, {"ru": "Прочий доход", "uk": "Інший дохід", "en": "Other income"}),
    ("goods", "expense", True, {"ru": "Закупка товара", "uk": "Закупівля товару", "en": "Goods for resale"}),
    ("materials", "expense", True, {"ru": "Материалы", "uk": "Матеріали", "en": "Materials"}),
    ("packaging", "expense", True, {"ru": "Упаковка", "uk": "Пакування", "en": "Packaging"}),
    ("rent", "expense", False, {"ru": "Аренда", "uk": "Оренда", "en": "Rent"}),
    ("salary", "expense", False, {"ru": "Зарплата", "uk": "Зарплата", "en": "Salaries"}),
    ("ads", "expense", False, {"ru": "Реклама", "uk": "Реклама", "en": "Advertising"}),
    ("delivery", "expense", False, {"ru": "Доставка и транспорт", "uk": "Доставка й транспорт", "en": "Delivery"}),
    ("services_it", "expense", False, {"ru": "Связь и сервисы", "uk": "Зв'язок і сервіси", "en": "Software & phone"}),
    ("taxes", "expense", False, {"ru": "Налоги и ЕСВ", "uk": "Податки та ЄСВ", "en": "Taxes"}),
    ("bank", "expense", False, {"ru": "Банк и комиссии", "uk": "Банк і комісії", "en": "Bank fees"}),
    ("other_expense", "expense", False, {"ru": "Прочее", "uk": "Інше", "en": "Other"}),
]
DEFAULT_ACCOUNTS = [{"ru": "Наличные", "uk": "Готівка", "en": "Cash"},
                    {"ru": "Карта ФОП", "uk": "Картка ФОП", "en": "Business card"}]

LANGS = ("uk", "ru", "en")


def lang_of(code: str | None) -> str:
    code = (code or "").lower()[:2]
    return code if code in LANGS else ("ru" if code in ("be", "kk") else "uk")


# ---------------------------------------------------------------- people and businesses

async def ensure_user(session: AsyncSession, telegram_id: int, first_name: str | None = None,
                      username: str | None = None, language_code: str | None = None) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        user = User(telegram_id=telegram_id, first_name=first_name or "", username=username,
                    language=lang_of(language_code))
        session.add(user)
        await session.flush()
    else:
        if first_name:
            user.first_name = first_name
        user.username = username
    return user


async def create_business(session: AsyncSession, user: User, name: str, kind: str = "fop",
                          fop_group: int | None = 3, is_vat_payer: bool = False, currency: str = "UAH",
                          timezone: str | None = None, tax_rate: Decimal | None = None,
                          language: str | None = None) -> tuple[Business, Member]:
    if kind not in ("fop", "company", "freelance"):
        raise HTTPException(422, "Unknown business type")
    if fop_group not in (None, 1, 2, 3):
        raise HTTPException(422, "FOP group must be 1, 2 or 3")
    if kind == "company":
        fop_group = None
    lang = language or user.language
    if tax_rate is None:
        tax_rate = finance.default_group3_rate(is_vat_payer) if fop_group == 3 else Decimal("0")
    business = Business(owner_user_id=user.id, owner_telegram_id=user.telegram_id, name=name.strip()[:120] or "Мій бізнес",
                        kind=kind, fop_group=fop_group, is_vat_payer=is_vat_payer, tax_rate=tax_rate,
                        currency=currency.upper(), timezone=timezone or get_settings().default_timezone)
    if user.pending_referral:
        referrer = await session.get(Business, user.pending_referral)
        if referrer and referrer.owner_telegram_id != user.telegram_id:
            business.referred_by_business_id = referrer.id
        user.pending_referral = None
    plans.start_trial(business)
    session.add(business)
    await session.flush()
    member = Member(business_id=business.id, telegram_id=user.telegram_id, name=user.first_name or "", role="owner")
    session.add(member)
    for key, ckind, cogs, names in DEFAULT_CATEGORIES:
        session.add(Category(business_id=business.id, name=names.get(lang, names["uk"]), kind=ckind, is_cogs=cogs, key=key))
    for names in DEFAULT_ACCOUNTS:
        session.add(Account(business_id=business.id, name=names.get(lang, names["uk"])))
    user.active_business_id = business.id
    await session.flush()
    return business, member


async def memberships(session: AsyncSession, telegram_id: int) -> list[tuple[Member, Business]]:
    rows = await session.execute(
        select(Member, Business).join(Business, Business.id == Member.business_id)
        .where(Member.telegram_id == telegram_id).order_by(Business.id))
    return [(m, b) for m, b in rows.all()]


async def context_for(session: AsyncSession, user: User, business_id: int | None = None
                      ) -> tuple[Business | None, Member | None]:
    """The business the person works in now (the requested one, the last used, or the first)."""
    rows = await memberships(session, user.telegram_id)
    if not rows:
        if business_id:
            raise HTTPException(403, "You are not a member of this business")
        return None, None
    wanted = business_id or user.active_business_id
    for member, business in rows:
        if business.id == wanted:
            if business_id and user.active_business_id != business_id:
                user.active_business_id = business_id
            return business, member
    if business_id:
        raise HTTPException(403, "You are not a member of this business")
    member, business = rows[0]
    user.active_business_id = business.id
    return business, member


# ---------------------------------------------------------------- lookups

async def owned(session: AsyncSession, model, business_id: int, row_id: int | None, *, required: bool = False):
    if row_id is None:
        if required:
            raise HTTPException(404, f"{model.__name__} not found")
        return None
    row = await session.get(model, row_id)
    if row is None or row.business_id != business_id:
        raise HTTPException(404, f"{model.__name__} not found")
    return row


async def categories(session: AsyncSession, business_id: int, kind: str | None = None) -> list[Category]:
    q = select(Category).where(Category.business_id == business_id, Category.archived.is_(False))
    if kind:
        q = q.where(Category.kind == kind)
    return list((await session.scalars(q.order_by(Category.kind, Category.id))).all())


async def resolve_category(session: AsyncSession, business_id: int, kind: str, key: str | None,
                           note: str = "") -> Category | None:
    cats = await categories(session, business_id, kind)
    if not cats:
        return None
    low = (note or "").lower()
    # A category the person created whose name appears in the note wins over the keyword table.
    for c in cats:
        stem = c.name.lower()[:max(4, len(c.name) - 2)]
        if stem and stem in low and c.key is None:
            return c
    if key:
        for c in cats:
            if c.key == key:
                return c
    for c in cats:
        stem = c.name.lower()[:max(4, len(c.name) - 2)]
        if stem and stem in low:
            return c
    fallback = "other_income" if kind == "income" else "other_expense"
    return next((c for c in cats if c.key == fallback), cats[-1])


async def find_counterparty(session: AsyncSession, business_id: int, name: str) -> Counterparty | None:
    name = (name or "").strip()
    if not name:
        return None
    rows = list((await session.scalars(select(Counterparty).where(Counterparty.business_id == business_id))).all())
    low = name.lower()
    for c in rows:
        if c.name.lower() == low:
            return c
    for c in rows:
        if c.name.lower().startswith(low) or low.startswith(c.name.lower()):
            return c
    for c in rows:
        if low[:5] and low[:5] in c.name.lower():
            return c
    return None


async def count_rows(session: AsyncSession, model, business_id: int, *where) -> int:
    q = select(func.count()).select_from(model).where(model.business_id == business_id, *where)
    return int(await session.scalar(q) or 0)


async def get_or_create_counterparty(session: AsyncSession, business: Business, name: str,
                                     kind: str = "client") -> Counterparty:
    found = await find_counterparty(session, business.id, name)
    if found:
        return found
    plans.check_count(business, "counterparties", await count_rows(session, Counterparty, business.id))
    row = Counterparty(business_id=business.id, name=name.strip()[:160], kind=kind)
    session.add(row)
    await session.flush()
    return row


# ---------------------------------------------------------------- operations

async def record_operation(session: AsyncSession, business: Business, member: Member | None, *, kind: str,
                           amount: Decimal, currency: str | None = None, category_id: int | None = None,
                           counterparty_id: int | None = None, project_id: int | None = None,
                           account_id: int | None = None, to_account_id: int | None = None,
                           note: str | None = None, occurred_at: date | None = None, source: str = "app",
                           bank_tx_id: str | None = None, product_id: int | None = None,
                           quantity: Decimal | None = None, attachment_file_id: str | None = None) -> Operation:
    if kind not in ("income", "expense", "transfer"):
        raise HTTPException(422, "kind must be income, expense or transfer")
    amount = q2(amount)
    if amount <= 0:
        raise HTTPException(422, "Amount must be positive")
    currency = (currency or business.currency).upper()
    category = await owned(session, Category, business.id, category_id)
    if category and category.kind != kind:
        raise HTTPException(422, "Category does not match the operation type")
    await owned(session, Counterparty, business.id, counterparty_id)
    await owned(session, Project, business.id, project_id)
    await owned(session, Account, business.id, account_id)
    if kind == "transfer":
        if not account_id or not to_account_id or account_id == to_account_id:
            raise HTTPException(422, "A transfer needs two different accounts")
        await owned(session, Account, business.id, to_account_id, required=True)
        category_id = counterparty_id = None
    day = occurred_at or finance.local_today(business.timezone)
    try:
        amount_base = await fx.convert(amount, currency, business.currency, day if day < date.today() else None)
    except fx.RateUnavailable as error:
        raise HTTPException(503, f"Exchange rate for {currency} is unavailable now, try later") from error
    op = Operation(business_id=business.id, member_id=member.id if member else None, kind=kind, amount=amount,
                   currency=currency, amount_base=amount_base, category_id=category.id if category else None,
                   counterparty_id=counterparty_id, project_id=project_id, account_id=account_id,
                   to_account_id=to_account_id if kind == "transfer" else None, note=(note or "").strip()[:500] or None,
                   occurred_at=day, source=source, bank_tx_id=bank_tx_id, attachment_file_id=attachment_file_id)
    if product_id:
        product = await owned(session, Product, business.id, product_id, required=True)
        qty = Decimal(quantity or 1)
        op.product_id, op.quantity = product.id, qty
        if kind == "income":
            product.stock_qty = Decimal(product.stock_qty or 0) - qty
            op.cogs_amount = q2(Decimal(product.cost_price or 0) * qty)
        elif kind == "expense":
            product.stock_qty = Decimal(product.stock_qty or 0) + qty
    session.add(op)
    await session.flush()
    return op


async def _undo_stock(session: AsyncSession, op: Operation) -> None:
    if op.product_id and op.quantity:
        product = await session.get(Product, op.product_id)
        if product:
            delta = Decimal(op.quantity)
            product.stock_qty = Decimal(product.stock_qty or 0) + (delta if op.kind == "income" else -delta)


async def delete_operation(session: AsyncSession, op: Operation) -> None:
    await _undo_stock(session, op)
    await session.delete(op)


async def update_operation(session: AsyncSession, business: Business, op: Operation, **fields) -> Operation:
    """Edit in place: validate like a new operation (a throw-away one), then copy the values over."""
    await _undo_stock(session, op)
    product_id, quantity = fields.pop("product_id", None), fields.pop("quantity", None)
    probe = await record_operation(session, business, None, source=op.source, **fields)
    for name in ("kind", "amount", "currency", "amount_base", "category_id", "counterparty_id", "project_id",
                 "account_id", "to_account_id", "note", "occurred_at"):
        setattr(op, name, getattr(probe, name))
    await session.delete(probe)
    op.product_id = op.quantity = op.cogs_amount = None
    if product_id:
        product = await owned(session, Product, business.id, product_id, required=True)
        qty = Decimal(quantity or 1)
        op.product_id, op.quantity = product.id, qty
        if op.kind == "income":
            product.stock_qty = Decimal(product.stock_qty or 0) - qty
            op.cogs_amount = q2(Decimal(product.cost_price or 0) * qty)
        elif op.kind == "expense":
            product.stock_qty = Decimal(product.stock_qty or 0) + qty
    await session.flush()
    return op


async def load_ops(session: AsyncSession, business_id: int, start: date | None, end: date | None,
                   member_id: int | None = None, project_id: int | None = None) -> list[Op]:
    q = (select(Operation.kind, Operation.amount_base, Operation.occurred_at, Category.is_cogs, Operation.cogs_amount,
                Operation.category_id, Operation.counterparty_id, Operation.project_id, Operation.member_id)
         .outerjoin(Category, Category.id == Operation.category_id)
         .where(Operation.business_id == business_id))
    if start:
        q = q.where(Operation.occurred_at >= start)
    if end:
        q = q.where(Operation.occurred_at <= end)
    if member_id:
        q = q.where(Operation.member_id == member_id)
    if project_id:
        q = q.where(Operation.project_id == project_id)
    rows = await session.execute(q)
    return [Op(kind=r[0], amount=Decimal(r[1]), occurred_at=r[2], is_cogs=bool(r[3]),
               cogs_amount=Decimal(r[4]) if r[4] is not None else None, category_id=r[5], counterparty_id=r[6],
               project_id=r[7], member_id=r[8]) for r in rows.all()]


async def account_balances(session: AsyncSession, business: Business) -> tuple[list[dict], Decimal]:
    accounts = list((await session.scalars(select(Account).where(Account.business_id == business.id,
                                                                  Account.archived.is_(False)).order_by(Account.id))).all())
    sums = {a.id: Decimal(a.opening_balance or 0) for a in accounts}
    rows = await session.execute(
        select(Operation.kind, Operation.account_id, Operation.to_account_id, func.sum(Operation.amount_base))
        .where(Operation.business_id == business.id)
        .group_by(Operation.kind, Operation.account_id, Operation.to_account_id))
    for kind, acc, to_acc, total in rows.all():
        total = Decimal(total or 0)
        if kind == "income" and acc in sums:
            sums[acc] += total
        elif kind == "expense" and acc in sums:
            sums[acc] -= total
        elif kind == "transfer":
            if acc in sums:
                sums[acc] -= total
            if to_acc in sums:
                sums[to_acc] += total
    # Operations without an account count towards the first account (the cash desk).
    unassigned = await session.execute(
        select(Operation.kind, func.sum(Operation.amount_base))
        .where(Operation.business_id == business.id, Operation.account_id.is_(None), Operation.kind != "transfer")
        .group_by(Operation.kind))
    loose = ZERO
    for kind, total in unassigned.all():
        loose += Decimal(total or 0) * (1 if kind == "income" else -1)
    if accounts:
        sums[accounts[0].id] += loose
    out = [{"id": a.id, "name": a.name, "bank": a.bank, "opening_balance": q2(a.opening_balance),
            "balance": q2(sums[a.id])} for a in accounts]
    return out, q2(sum(sums.values(), ZERO) if accounts else loose)


# ---------------------------------------------------------------- taxes

def tax_profile(business: Business) -> TaxProfile:
    return TaxProfile(kind=business.kind, fop_group=business.fop_group, tax_rate=Decimal(business.tax_rate or 0),
                      is_vat_payer=business.is_vat_payer, pays_esv=business.pays_esv)


async def income_between(session: AsyncSession, business_id: int, start: date, end: date) -> Decimal:
    total = await session.scalar(select(func.sum(Operation.amount_base)).where(
        Operation.business_id == business_id, Operation.kind == "income",
        Operation.occurred_at >= start, Operation.occurred_at <= end))
    return q2(total or 0)


async def tax_overview(session: AsyncSession, business: Business, today: date | None = None,
                       year: int | None = None) -> dict:
    """Quarters of a year with taxes (kept in TaxPeriod, paid status preserved), upcoming payments, limit."""
    today = today or finance.local_today(business.timezone)
    year = year or today.year
    profile = tax_profile(business)
    if not profile.is_fop:
        return {"applicable": False, "quarters": [], "upcoming": [], "limit": None}
    stored = {t.period: t for t in (await session.scalars(
        select(TaxPeriod).where(TaxPeriod.business_id == business.id))).all()}
    quarters = []
    incomes: dict[tuple[int, int], Decimal] = {}
    for y in sorted({year, today.year, today.year - 1 if finance.quarter_of(today) == 1 else today.year}):
        for q in range(1, 5):
            start, end = finance.quarter_range(y, q)
            if start > today:
                continue
            incomes[(y, q)] = await income_between(session, business.id, start, end)
    for q in range(1, 5):
        start, end = finance.quarter_range(year, q)
        income = incomes.get((year, q), ZERO)
        t = finance.quarter_taxes(profile, year, q, income)
        if start > today:
            t["future"] = True
        row = stored.get(t["period"])
        if start <= today:
            if row is None:
                row = TaxPeriod(business_id=business.id, period=t["period"])
                session.add(row)
                stored[t["period"]] = row
            row.income_total, row.single_tax, row.esv = t["income_total"], t["single_tax"], t["esv"]
            row.military_levy, row.due_date = t["military_levy"], t["due_date"]
            t["id"] = None
        t["status"] = row.status if row else "due"
        t["paid_at"] = row.paid_at if row else None
        quarters.append(t)
    await session.flush()
    for t in quarters:
        row = stored.get(t["period"])
        t["id"] = row.id if row else None
    paid = {p for p, r in stored.items() if r.status == "paid"}
    upcoming = finance.upcoming_payments(profile, today, incomes, paid)
    ytd = await income_between(session, business.id, date(today.year, 1, 1), today)
    return {"applicable": True, "group": business.fop_group, "rate": q2(business.tax_rate), "year": year,
            "quarters": quarters, "upcoming": upcoming, "limit": finance.income_limit(profile, today.year, ytd)}


# ---------------------------------------------------------------- dashboard

async def attention(session: AsyncSession, business: Business, today: date) -> list[dict]:
    items: list[dict] = []
    invoices = (await session.scalars(select(Invoice).where(
        Invoice.business_id == business.id, Invoice.status.in_(("sent", "overdue")),
        Invoice.due_date.is_not(None), Invoice.due_date < today))).all()
    names = await counterparty_names(session, business.id)
    for inv in invoices:
        items.append({"kind": "invoice_overdue", "id": inv.id, "number": inv.number, "amount": q2(inv.total),
                      "counterparty": names.get(inv.counterparty_id), "days": (today - inv.due_date).days})
    debts = (await session.scalars(select(Debt).where(
        Debt.business_id == business.id, Debt.status == "open", Debt.direction == "they_owe",
        Debt.due_date.is_not(None), Debt.due_date < today))).all()
    for d in debts:
        items.append({"kind": "debt_overdue", "id": d.id, "amount": q2(d.amount),
                      "counterparty": names.get(d.counterparty_id), "days": (today - d.due_date).days})
    if plans.limits_for(business)["forecast"]:
        gap = await cash_gap(session, business, today)
        if gap:
            items.append({"kind": "cash_gap", **gap})
    return items


async def counterparty_names(session: AsyncSession, business_id: int) -> dict[int, str]:
    rows = await session.execute(select(Counterparty.id, Counterparty.name).where(Counterparty.business_id == business_id))
    return dict(rows.all())


async def cash_gap(session: AsyncSession, business: Business, today: date) -> dict | None:
    _, total = await account_balances(session, business)
    rec = (await session.scalars(select(RecurringOperation).where(
        RecurringOperation.business_id == business.id, RecurringOperation.active.is_(True)))).all()
    items = [{"kind": r.kind, "amount": r.amount, "day_of_month": r.day_of_month, "note": r.note} for r in rec]
    return finance.cash_gap(total, today, items)


async def dashboard(session: AsyncSession, business: Business, member: Member, period: str,
                    today: date | None = None) -> dict:
    today = today or finance.local_today(business.timezone)
    if period not in finance.PERIODS:
        raise HTTPException(422, "Unknown period")
    start, end = finance.period_range(period, today)
    plans.check_history(business, start, today)
    own = member.id if member.role == "staff" else None
    current = finance.summarize(await load_ops(session, business.id, start, min(end, today), own))
    prev_start, prev_end = finance.previous_comparable(period, today)
    try:
        plans.check_history(business, prev_start, today)
        previous = finance.summarize(await load_ops(session, business.id, prev_start, prev_end, own))
    except HTTPException:
        previous = None
    chart_start, chart_end = (start, end) if period != "today" else (today - timedelta(days=6), today)
    if period == "year":
        series = finance.monthly_series(await load_ops(session, business.id, start, end, own), start, end)
    else:
        series = finance.daily_series(await load_ops(session, business.id, chart_start, chart_end, own),
                                      chart_start, chart_end)

    def change(name: str):
        if previous is None:
            return None
        return finance.pct_change(getattr(current, name), getattr(previous, name))

    data = {
        "period": period, "start": start, "end": end,
        "summary": current.as_dict(),
        "previous": previous.as_dict() if previous else None,
        "change": {"revenue": change("revenue"), "expenses": change("expenses"), "profit": change("profit")},
        "series": series, "series_kind": "month" if period == "year" else "day",
    }
    if member.role == "staff":
        return data
    accounts, total = await account_balances(session, business)
    taxes = await tax_overview(session, business, today)
    data.update({
        "accounts": accounts, "balance": total,
        "tax": {"applicable": taxes["applicable"], "next": taxes["upcoming"][:3], "limit": taxes["limit"]},
        "attention": await attention(session, business, today),
    })
    if plans.limits_for(business)["forecast"] and period == "month":
        month_revenue = finance.summarize(await load_ops(session, business.id, *finance.period_range("month", today))).revenue
        data["forecast"] = {"revenue_month_end": finance.forecast_month_end(month_revenue, today)}
    return data


# ---------------------------------------------------------------- recurring

async def apply_due_recurring(session: AsyncSession, business: Business, today: date | None = None) -> int:
    today = today or finance.local_today(business.timezone)
    rows = (await session.scalars(select(RecurringOperation).where(
        RecurringOperation.business_id == business.id, RecurringOperation.active.is_(True),
        RecurringOperation.next_date <= today))).all()
    created = 0
    for r in rows:
        guard = 0
        while r.next_date <= today and guard < 12:
            try:
                await record_operation(session, business, None, kind=r.kind, amount=r.amount, category_id=r.category_id,
                                       account_id=r.account_id, counterparty_id=r.counterparty_id, note=r.note,
                                       occurred_at=r.next_date, source="recurring")
                created += 1
            except HTTPException:
                r.active = False
                break
            y, m = finance.shift_month(r.next_date.year, r.next_date.month, 1)
            r.next_date = finance.next_occurrence(r.day_of_month, date(y, m, 1))
            guard += 1
    return created


# ---------------------------------------------------------------- notices (sent reminders)

def notices(business: Business) -> set[str]:
    try:
        return set(json.loads(business.notices or "[]"))
    except ValueError:
        return set()


def add_notice(business: Business, key: str) -> None:
    keys = sorted(notices(business) | {key})[-200:]
    business.notices = json.dumps(keys)


# ---------------------------------------------------------------- operations list

async def list_operations(session: AsyncSession, business: Business, member: Member, *, kind: str | None = None,
                          category_id: int | None = None, project_id: int | None = None,
                          counterparty_id: int | None = None, member_id: int | None = None, q: str | None = None,
                          date_from: date | None = None, date_to: date | None = None, limit: int = 50,
                          offset: int = 0) -> list[Operation]:
    query = select(Operation).where(Operation.business_id == business.id)
    if member.role == "staff":
        query = query.where(Operation.member_id == member.id)
    elif member_id:
        query = query.where(Operation.member_id == member_id)
    if kind:
        query = query.where(Operation.kind == kind)
    if category_id:
        query = query.where(Operation.category_id == category_id)
    if project_id:
        query = query.where(Operation.project_id == project_id)
    if counterparty_id:
        query = query.where(Operation.counterparty_id == counterparty_id)
    if date_from:
        query = query.where(Operation.occurred_at >= date_from)
    if date_to:
        query = query.where(Operation.occurred_at <= date_to)
    first = plans.history_start(business, finance.local_today(business.timezone))
    if first:
        query = query.where(Operation.occurred_at >= first)
    if q:
        like = f"%{q.strip().lower()}%"
        cp_ids = select(Counterparty.id).where(Counterparty.business_id == business.id,
                                               func.lower(Counterparty.name).like(like))
        query = query.where(or_(func.lower(Operation.note).like(like), Operation.counterparty_id.in_(cp_ids)))
    query = query.order_by(Operation.occurred_at.desc(), Operation.id.desc()).limit(min(limit, 200)).offset(offset)
    return list((await session.scalars(query)).all())


def op_dict(op: Operation) -> dict:
    return {"id": op.id, "kind": op.kind, "amount": q2(op.amount), "currency": op.currency,
            "amount_base": q2(op.amount_base), "category_id": op.category_id, "counterparty_id": op.counterparty_id,
            "project_id": op.project_id, "account_id": op.account_id, "to_account_id": op.to_account_id,
            "note": op.note, "occurred_at": op.occurred_at, "source": op.source, "member_id": op.member_id,
            "has_attachment": bool(op.attachment_file_id), "product_id": op.product_id,
            "quantity": op.quantity, "cogs_amount": op.cogs_amount}


__all__ = ["and_"]
