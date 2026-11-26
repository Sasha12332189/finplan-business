"""Mini App JSON API. Every route checks membership and role on the server (app/auth.py, app/plans.py)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from . import finance, plans, services
from .auth import Ctx, get_ctx
from .models import (
    Account, Category, Counterparty, Member, Operation, Project, RecurringOperation, TaxPeriod, utcnow,
)
from .services import owned, q2
from .tax_rates import DISCLAIMER

api = APIRouter(prefix="/api")

CURRENCIES = ("UAH", "USD", "EUR", "PLN", "GBP")


def need(ctx: Ctx, action: str):
    business, member = ctx.need_business()
    plans.require(member.role, action)
    return business, member


# ---------------------------------------------------------------- me / business

def business_dict(b, member: Member | None = None) -> dict:
    return {"id": b.id, "name": b.name, "kind": b.kind, "fop_group": b.fop_group, "tax_rate": q2(b.tax_rate),
            "is_vat_payer": b.is_vat_payer, "pays_esv": b.pays_esv, "currency": b.currency, "timezone": b.timezone,
            "daily_digest": b.daily_digest, "weekly_digest": b.weekly_digest, "monthly_report": b.monthly_report,
            "role": member.role if member else None}


@api.get("/me")
async def me(ctx: Ctx = Depends(get_ctx)) -> dict:
    rows = await services.memberships(ctx.session, ctx.user.telegram_id)
    from .config import get_settings
    out = {
        "user": {"telegram_id": ctx.user.telegram_id, "first_name": ctx.user.first_name,
                 "language": ctx.user.language, "theme": ctx.user.theme},
        "businesses": [{"id": b.id, "name": b.name, "role": m.role} for m, b in rows],
        "business": business_dict(ctx.business, ctx.member) if ctx.business else None,
        "plan": plans.status(ctx.business) if ctx.business else None,
        "permissions": sorted(plans.PERMISSIONS.get(ctx.role, ())),
        "disclaimer": DISCLAIMER,
        "personal_app_url": get_settings().personal_app_url or None,
        "today": finance.local_today(ctx.business.timezone) if ctx.business else date.today(),
    }
    return out


class UserUpdate(BaseModel):
    language: Literal["uk", "ru", "en"] | None = None
    theme: Literal["system", "light", "dark"] | None = None


@api.patch("/me")
async def update_me(body: UserUpdate, ctx: Ctx = Depends(get_ctx)) -> dict:
    if body.language:
        ctx.user.language = body.language
    if body.theme:
        ctx.user.theme = body.theme
    await ctx.session.commit()
    return {"ok": True}


class BusinessIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["fop", "company", "freelance"] = "fop"
    fop_group: int | None = Field(default=3, ge=1, le=3)
    is_vat_payer: bool = False
    currency: str = "UAH"

    @field_validator("currency")
    @classmethod
    def _cur(cls, v: str) -> str:
        v = v.upper()
        if v not in CURRENCIES:
            raise ValueError("Unsupported currency")
        return v


@api.post("/business")
async def create_business(body: BusinessIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, member = await services.create_business(ctx.session, ctx.user, body.name, body.kind, body.fop_group,
                                                      body.is_vat_payer, body.currency)
    await ctx.session.commit()
    return business_dict(business, member)


class BusinessUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: Literal["fop", "company", "freelance"] | None = None
    fop_group: int | None = Field(default=None, ge=0, le=3)  # 0 = not a FOP
    tax_rate: Decimal | None = Field(default=None, ge=0, le=50)
    is_vat_payer: bool | None = None
    pays_esv: bool | None = None
    currency: str | None = None
    timezone: str | None = None
    daily_digest: bool | None = None
    weekly_digest: bool | None = None
    monthly_report: bool | None = None


@api.patch("/business")
async def update_business(body: BusinessUpdate, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, member = need(ctx, "manage")
    data = body.model_dump(exclude_unset=True)
    if "currency" in data:
        cur = (data["currency"] or "").upper()
        if cur not in CURRENCIES:
            raise HTTPException(422, "Unsupported currency")
        if cur != business.currency and await services.count_rows(ctx.session, Operation, business.id):
            raise HTTPException(409, "The currency cannot change once operations exist")
        data["currency"] = cur
    if "timezone" in data:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(data["timezone"])
        except Exception as error:
            raise HTTPException(422, "Unknown time zone") from error
    if "fop_group" in data:
        data["fop_group"] = data["fop_group"] or None
        if data["fop_group"] == 3 and "tax_rate" not in data and not business.tax_rate:
            data["tax_rate"] = finance.default_group3_rate(data.get("is_vat_payer", business.is_vat_payer))
    if data.get("is_vat_payer") is not None and "tax_rate" not in data and business.fop_group == 3:
        data["tax_rate"] = finance.default_group3_rate(data["is_vat_payer"])
    for key, value in data.items():
        setattr(business, key, value)
    if business.kind == "company":
        business.fop_group = None
    await ctx.session.commit()
    return business_dict(business, member)


# ---------------------------------------------------------------- lookups

def category_dict(c: Category) -> dict:
    return {"id": c.id, "name": c.name, "kind": c.kind, "is_cogs": c.is_cogs, "key": c.key}


@api.get("/meta")
async def meta(ctx: Ctx = Depends(get_ctx)) -> dict:
    business, member = ctx.need_business()
    s = ctx.session
    cats = await services.categories(s, business.id)
    accounts, total = await services.account_balances(s, business) if plans.can(member.role, "read") else ([], None)
    if not accounts:
        accounts = [{"id": a.id, "name": a.name, "bank": a.bank} for a in (await s.scalars(
            select(Account).where(Account.business_id == business.id, Account.archived.is_(False)))).all()]
    projects = (await s.scalars(select(Project).where(Project.business_id == business.id).order_by(Project.id))).all()
    cps = (await s.scalars(select(Counterparty).where(Counterparty.business_id == business.id).order_by(Counterparty.name))).all()
    members = (await s.scalars(select(Member).where(Member.business_id == business.id).order_by(Member.id))).all()
    return {
        "categories": [category_dict(c) for c in cats],
        "accounts": accounts, "balance": total,
        "projects": [{"id": p.id, "name": p.name, "archived": p.archived} for p in projects],
        "counterparties": [counterparty_dict(c) for c in cps],
        "members": [{"id": m.id, "name": m.name, "role": m.role, "telegram_id": m.telegram_id} for m in members],
        "currencies": CURRENCIES,
    }


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["income", "expense"]
    is_cogs: bool = False


@api.post("/categories")
async def add_category(body: CategoryIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    row = Category(business_id=business.id, name=body.name.strip(), kind=body.kind,
                   is_cogs=body.is_cogs and body.kind == "expense")
    ctx.session.add(row)
    await ctx.session.commit()
    return category_dict(row)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_cogs: bool | None = None


@api.patch("/categories/{row_id}")
async def update_category(row_id: int, body: CategoryUpdate, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    row = await owned(ctx.session, Category, business.id, row_id, required=True)
    if body.name:
        row.name = body.name.strip()
    if body.is_cogs is not None:
        row.is_cogs = body.is_cogs and row.kind == "expense"
    await ctx.session.commit()
    return category_dict(row)


@api.delete("/categories/{row_id}")
async def delete_category(row_id: int, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    row = await owned(ctx.session, Category, business.id, row_id, required=True)
    row.archived = True  # operations keep their category
    await ctx.session.commit()
    return {"ok": True}


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    opening_balance: Decimal = Decimal("0")


@api.post("/accounts")
async def add_account(body: AccountIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    row = Account(business_id=business.id, name=body.name.strip(), opening_balance=q2(body.opening_balance))
    ctx.session.add(row)
    await ctx.session.commit()
    return {"id": row.id, "name": row.name}


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    opening_balance: Decimal | None = None


@api.patch("/accounts/{row_id}")
async def update_account(row_id: int, body: AccountUpdate, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    row = await owned(ctx.session, Account, business.id, row_id, required=True)
    if body.name:
        row.name = body.name.strip()
    if body.opening_balance is not None:
        row.opening_balance = q2(body.opening_balance)
    await ctx.session.commit()
    return {"id": row.id, "name": row.name}


@api.delete("/accounts/{row_id}")
async def delete_account(row_id: int, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    row = await owned(ctx.session, Account, business.id, row_id, required=True)
    row.archived = True
    await ctx.session.commit()
    return {"ok": True}


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    archived: bool = False


@api.post("/projects")
async def add_project(body: ProjectIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    plans.check_count(business, "projects", await services.count_rows(ctx.session, Project, business.id,
                                                                      Project.archived.is_(False)))
    row = Project(business_id=business.id, name=body.name.strip())
    ctx.session.add(row)
    await ctx.session.commit()
    return {"id": row.id, "name": row.name, "archived": False}


@api.patch("/projects/{row_id}")
async def update_project(row_id: int, body: ProjectIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    row = await owned(ctx.session, Project, business.id, row_id, required=True)
    row.name, row.archived = body.name.strip(), body.archived
    await ctx.session.commit()
    return {"id": row.id, "name": row.name, "archived": row.archived}


def counterparty_dict(c: Counterparty) -> dict:
    return {"id": c.id, "name": c.name, "kind": c.kind, "phone": c.phone, "tax_id": c.tax_id,
            "telegram_username": c.telegram_username, "note": c.note}


class CounterpartyIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    kind: Literal["client", "supplier", "both"] = "client"
    phone: str | None = Field(default=None, max_length=40)
    tax_id: str | None = Field(default=None, max_length=20)
    telegram_username: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=1000)


@api.post("/counterparties")
async def add_counterparty(body: CounterpartyIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, member = ctx.need_business()
    if not (plans.can(member.role, "write") or plans.can(member.role, "add_operation")):
        plans.require(member.role, "write")
    plans.check_count(business, "counterparties", await services.count_rows(ctx.session, Counterparty, business.id))
    row = Counterparty(business_id=business.id, **body.model_dump())
    row.name = row.name.strip()
    if row.telegram_username:
        row.telegram_username = row.telegram_username.lstrip("@")
    ctx.session.add(row)
    await ctx.session.commit()
    return counterparty_dict(row)


@api.patch("/counterparties/{row_id}")
async def update_counterparty(row_id: int, body: CounterpartyIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "write")
    row = await owned(ctx.session, Counterparty, business.id, row_id, required=True)
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    if row.telegram_username:
        row.telegram_username = row.telegram_username.lstrip("@")
    await ctx.session.commit()
    return counterparty_dict(row)


@api.delete("/counterparties/{row_id}")
async def delete_counterparty(row_id: int, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "write")
    row = await owned(ctx.session, Counterparty, business.id, row_id, required=True)
    await ctx.session.execute(Operation.__table__.update().where(Operation.counterparty_id == row.id)
                              .values(counterparty_id=None))
    await ctx.session.delete(row)
    await ctx.session.commit()
    return {"ok": True}


# ---------------------------------------------------------------- dashboard

@api.get("/dashboard")
async def dashboard(period: str = "month", ctx: Ctx = Depends(get_ctx)) -> dict:
    business, member = ctx.need_business()
    plans.require(member.role, "read_own")
    data = await services.dashboard(ctx.session, business, member, period)
    await ctx.session.commit()
    return data


# ---------------------------------------------------------------- operations

class OperationIn(BaseModel):
    kind: Literal["income", "expense", "transfer"]
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str | None = None
    category_id: int | None = None
    counterparty_id: int | None = None
    project_id: int | None = None
    account_id: int | None = None
    to_account_id: int | None = None
    note: str | None = Field(default=None, max_length=500)
    occurred_at: date | None = None
    product_id: int | None = None
    quantity: Decimal | None = Field(default=None, gt=0)


@api.get("/operations")
async def operations(kind: str | None = None, category_id: int | None = None, project_id: int | None = None,
                     counterparty_id: int | None = None, member_id: int | None = None, q: str | None = None,
                     date_from: date | None = None, date_to: date | None = None, limit: int = 50, offset: int = 0,
                     ctx: Ctx = Depends(get_ctx)) -> dict:
    business, member = ctx.need_business()
    plans.require(member.role, "read_own")
    rows = await services.list_operations(ctx.session, business, member, kind=kind, category_id=category_id,
                                          project_id=project_id, counterparty_id=counterparty_id, member_id=member_id,
                                          q=q, date_from=date_from, date_to=date_to, limit=limit, offset=offset)
    first = plans.history_start(business, finance.local_today(business.timezone))
    return {"items": [services.op_dict(o) for o in rows], "history_from": first}


def check_staff_date(member: Member, business, day: date | None) -> None:
    if day and day > finance.local_today(business.timezone).replace(year=finance.local_today(business.timezone).year + 1):
        raise HTTPException(422, "Date is too far in the future")


@api.post("/operations")
async def add_operation(body: OperationIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, member = need(ctx, "add_operation")
    check_staff_date(member, business, body.occurred_at)
    op = await services.record_operation(ctx.session, business, member, source="app", **body.model_dump())
    await ctx.session.commit()
    return services.op_dict(op)


async def editable(ctx: Ctx, op_id: int) -> Operation:
    business, member = ctx.need_business()
    op = await owned(ctx.session, Operation, business.id, op_id, required=True)
    if plans.can(member.role, "write"):
        return op
    if member.role == "staff" and op.member_id == member.id:
        return op
    plans.require(member.role, "write")
    return op


@api.patch("/operations/{op_id}")
async def update_operation(op_id: int, body: OperationIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    op = await editable(ctx, op_id)
    business, _ = ctx.need_business()
    await services.update_operation(ctx.session, business, op, **body.model_dump())
    await ctx.session.commit()
    return services.op_dict(op)


@api.delete("/operations/{op_id}")
async def delete_operation(op_id: int, ctx: Ctx = Depends(get_ctx)) -> dict:
    op = await editable(ctx, op_id)
    await services.delete_operation(ctx.session, op)
    await ctx.session.commit()
    return {"ok": True}


# ---------------------------------------------------------------- recurring

class RecurringIn(BaseModel):
    kind: Literal["income", "expense"] = "expense"
    amount: Decimal = Field(gt=0)
    category_id: int | None = None
    account_id: int | None = None
    counterparty_id: int | None = None
    note: str | None = Field(default=None, max_length=200)
    day_of_month: int = Field(ge=1, le=31)
    active: bool = True


def recurring_dict(r: RecurringOperation) -> dict:
    return {"id": r.id, "kind": r.kind, "amount": q2(r.amount), "category_id": r.category_id,
            "account_id": r.account_id, "counterparty_id": r.counterparty_id, "note": r.note,
            "day_of_month": r.day_of_month, "next_date": r.next_date, "active": r.active}


@api.get("/recurring")
async def recurring(ctx: Ctx = Depends(get_ctx)) -> list[dict]:
    business, _ = need(ctx, "read")
    rows = (await ctx.session.scalars(select(RecurringOperation).where(
        RecurringOperation.business_id == business.id).order_by(RecurringOperation.day_of_month))).all()
    return [recurring_dict(r) for r in rows]


@api.post("/recurring")
async def add_recurring(body: RecurringIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    await owned(ctx.session, Category, business.id, body.category_id)
    await owned(ctx.session, Account, business.id, body.account_id)
    await owned(ctx.session, Counterparty, business.id, body.counterparty_id)
    today = finance.local_today(business.timezone)
    row = RecurringOperation(business_id=business.id, **body.model_dump(),
                             next_date=finance.next_occurrence(body.day_of_month, today + timedelta(days=1)))
    ctx.session.add(row)
    await ctx.session.commit()
    return recurring_dict(row)


@api.patch("/recurring/{row_id}")
async def update_recurring(row_id: int, body: RecurringIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    row = await owned(ctx.session, RecurringOperation, business.id, row_id, required=True)
    await owned(ctx.session, Category, business.id, body.category_id)
    await owned(ctx.session, Account, business.id, body.account_id)
    day_changed = body.day_of_month != row.day_of_month
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    if day_changed:
        row.next_date = finance.next_occurrence(body.day_of_month, finance.local_today(business.timezone)
                                                + timedelta(days=1))
    await ctx.session.commit()
    return recurring_dict(row)


@api.delete("/recurring/{row_id}")
async def delete_recurring(row_id: int, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    row = await owned(ctx.session, RecurringOperation, business.id, row_id, required=True)
    await ctx.session.delete(row)
    await ctx.session.commit()
    return {"ok": True}


# ---------------------------------------------------------------- taxes

@api.get("/tax")
async def tax(year: int | None = None, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "read")
    data = await services.tax_overview(ctx.session, business, year=year)
    await ctx.session.commit()
    return data


class TaxPaid(BaseModel):
    paid: bool = True


@api.post("/tax/{period}/paid")
async def tax_paid(period: str, body: TaxPaid, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "write")
    row = await ctx.session.scalar(select(TaxPeriod).where(TaxPeriod.business_id == business.id,
                                                           TaxPeriod.period == period))
    if row is None:
        raise HTTPException(404, "Tax period not found")
    row.status = "paid" if body.paid else "due"
    row.paid_at = utcnow() if body.paid else None
    await ctx.session.commit()
    return {"ok": True, "status": row.status}


__all__ = ["api", "func"]
