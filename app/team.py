"""Stage 4: team members and roles (one-time expiring invite links), stock, referrals."""
from __future__ import annotations

import html
import secrets
from datetime import timedelta
from decimal import Decimal
from typing import Literal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from . import plans, runtime, services
from .api import need
from .auth import Ctx, get_ctx
from .bot import load
from .database import SessionLocal
from .finance import q2
from .models import Business, Invite, Member, Product, User, utcnow

INVITE_TTL = timedelta(days=2)
ROLE_NAMES = {"ru": {"owner": "Владелец", "admin": "Администратор", "staff": "Сотрудник", "accountant": "Бухгалтер"},
              "uk": {"owner": "Власник", "admin": "Адміністратор", "staff": "Працівник", "accountant": "Бухгалтер"}}


def role_name(lang: str, role: str) -> str:
    return ROLE_NAMES["ru" if lang == "ru" else "uk"][role]


# ---------------------------------------------------------------- invites

async def seats_used(session, business: Business) -> int:
    members = await services.count_rows(session, Member, business.id)
    pending = int(await session.scalar(select(func.count()).select_from(Invite).where(
        Invite.business_id == business.id, Invite.used_at.is_(None), Invite.expires_at > utcnow())) or 0)
    return members + pending


async def create_invite(session, business: Business, member: Member, role: str) -> Invite:
    plans.require(member.role, "team")
    if role == "owner" or role not in plans.ROLES:
        raise HTTPException(422, "Unknown role")
    if member.role == "admin" and role == "admin":
        raise HTTPException(403, "Only the owner can invite admins")
    limits = plans.limits_for(business)
    if role not in limits["roles"]:
        raise plans.upgrade_error(business, "roles", value=role)
    plans.check_count(business, "members", await seats_used(session, business))
    if role == "accountant" and plans.effective_plan(business) == "pro":
        exists = await session.scalar(select(func.count()).select_from(Member).where(
            Member.business_id == business.id, Member.role == "accountant"))
        if exists:
            raise plans.upgrade_error(business, "members", limits["members"])
    invite = Invite(business_id=business.id, token=secrets.token_urlsafe(18), role=role,
                    created_by_member_id=member.id, expires_at=utcnow() + INVITE_TTL)
    session.add(invite)
    await session.flush()
    return invite


def invite_link(invite: Invite) -> str | None:
    if not runtime.bot_username:
        return None
    return f"https://t.me/{runtime.bot_username}?start=inv_{invite.token}"


async def accept_invite(session, user: User, token: str) -> str:
    """Called from /start inv_<token>. One-time and expiring."""
    lang = user.language
    ru = lang == "ru"
    invite = await session.scalar(select(Invite).where(Invite.token == token))
    if invite is None or invite.used_at is not None or invite.expires_at < utcnow():
        return "Приглашение недействительно или устарело. Попросите новое." if ru else \
            "Запрошення недійсне або застаріло. Попросіть нове."
    business = await session.get(Business, invite.business_id)
    existing = await session.scalar(select(Member).where(Member.business_id == business.id,
                                                         Member.telegram_id == user.telegram_id))
    if existing:
        invite.used_at, invite.used_by_telegram_id = utcnow(), user.telegram_id
        user.active_business_id = business.id
        return (f"Вы уже в команде «{html.escape(business.name)}»." if ru else
                f"Ви вже в команді «{html.escape(business.name)}».")
    session.add(Member(business_id=business.id, telegram_id=user.telegram_id, name=user.first_name or "", role=invite.role))
    invite.used_at, invite.used_by_telegram_id = utcnow(), user.telegram_id
    user.active_business_id = business.id
    tips = {"staff": ("Записывайте операции сообщениями: <code>4500 продажа</code>.",
                      "Записуйте операції повідомленнями: <code>4500 продаж</code>."),
            "accountant": ("Вам доступны отчёты и выгрузки: /report, налоги: /tax.",
                           "Вам доступні звіти й вивантаження: /report, податки: /tax."),
            "admin": ("Вы можете вести учёт, счета и команду.", "Ви можете вести облік, рахунки й команду.")}[invite.role]
    owner_note = f"«{html.escape(business.name)}» — {role_name(lang, invite.role).lower()}."
    if runtime.bot:
        try:
            await runtime.bot.send_message(business.owner_telegram_id,
                                           f"{html.escape(user.first_name or 'Новий учасник')} приєднався(лась) до команди як "
                                           f"{role_name('uk', invite.role).lower()}.")
        except Exception:
            pass
    return (f"Добро пожаловать в команду {owner_note}\n{tips[0]}" if ru else f"Ласкаво просимо до команди {owner_note}\n{tips[1]}")


# ---------------------------------------------------------------- bot: /team

router = Router(name="team")


@router.message(Command("team"))
async def team_cmd(message: Message) -> None:
    async with SessionLocal() as session:
        user, business, member = await load(session, message)
        await session.commit()
    lang = user.language
    if business is None or not plans.can(member.role, "team"):
        await message.answer("Команду настраивает владелец бизнеса." if lang == "ru" else "Команду налаштовує власник бізнесу.")
        return
    allowed = [r for r in ("staff", "accountant", "admin") if r in plans.limits_for(business)["roles"]]
    if not allowed:
        await message.answer("Сотрудники — в Pro (бухгалтер) и Team (до 10 человек с ролями): /premium" if lang == "ru" else
                             "Працівники — у Pro (бухгалтер) і Team (до 10 людей з ролями): /premium")
        return
    rows = [[InlineKeyboardButton(text=role_name(lang, r), callback_data=f"inv:{r}")] for r in allowed]
    await message.answer("Кого пригласить? Ссылка одноразовая, действует 2 дня." if lang == "ru" else
                         "Кого запросити? Посилання одноразове, діє 2 дні.",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("inv:"))
async def team_invite(callback: CallbackQuery) -> None:
    role = callback.data.split(":", 1)[1]
    async with SessionLocal() as session:
        user, business, member = await load(session, callback)
        try:
            invite = await create_invite(session, business, member, role)
        except HTTPException as error:
            await session.rollback()
            await callback.answer("Лимит тарифа: /premium" if error.status_code == 402 else "Нет прав", show_alert=True)
            return
        await session.commit()
    link = invite_link(invite)
    await callback.answer()
    await callback.message.answer(
        (f"Ссылка для роли «{role_name(user.language, role)}» (одноразовая, 2 дня):\n{link}" if user.language == "ru" else
         f"Посилання для ролі «{role_name(user.language, role)}» (одноразове, 2 дні):\n{link}") if link else "Бот ещё не готов, попробуйте позже.")


# ---------------------------------------------------------------- API: team

api = APIRouter(prefix="/api")


@api.get("/team")
async def team(ctx: Ctx = Depends(get_ctx)) -> dict:
    business, member = need(ctx, "read")
    members = (await ctx.session.scalars(select(Member).where(Member.business_id == business.id).order_by(Member.id))).all()
    invites = (await ctx.session.scalars(select(Invite).where(
        Invite.business_id == business.id, Invite.used_at.is_(None), Invite.expires_at > utcnow()))).all()
    limits = plans.limits_for(business)
    return {"members": [{"id": m.id, "name": m.name, "role": m.role, "me": m.id == member.id} for m in members],
            "invites": [{"id": i.id, "role": i.role, "expires_at": i.expires_at, "link": invite_link(i)} for i in invites]
            if plans.can(member.role, "team") else [],
            "limit": limits["members"], "roles": list(limits["roles"]), "can_manage": plans.can(member.role, "team")}


class InviteIn(BaseModel):
    role: Literal["admin", "staff", "accountant"]


@api.post("/team/invites")
async def new_invite(body: InviteIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, member = need(ctx, "team")
    invite = await create_invite(ctx.session, business, member, body.role)
    await ctx.session.commit()
    link = invite_link(invite)
    if not link:
        raise HTTPException(503, "The bot is not connected yet, try again in a minute")
    return {"id": invite.id, "role": invite.role, "link": link, "expires_at": invite.expires_at}


@api.delete("/team/invites/{invite_id}")
async def cancel_invite(invite_id: int, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "team")
    invite = await services.owned(ctx.session, Invite, business.id, invite_id, required=True)
    await ctx.session.delete(invite)
    await ctx.session.commit()
    return {"ok": True}


class RoleIn(BaseModel):
    role: Literal["admin", "staff", "accountant"]


@api.patch("/team/members/{member_id}")
async def change_role(member_id: int, body: RoleIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, me = need(ctx, "team")
    target = await services.owned(ctx.session, Member, business.id, member_id, required=True)
    if target.role == "owner":
        raise HTTPException(403, "The owner's role cannot change")
    if me.role != "owner" and "admin" in (target.role, body.role):
        raise HTTPException(403, "Only the owner can manage admins")
    if body.role not in plans.limits_for(business)["roles"]:
        raise plans.upgrade_error(business, "roles", value=body.role)
    target.role = body.role
    await ctx.session.commit()
    return {"id": target.id, "role": target.role}


@api.delete("/team/members/{member_id}")
async def remove_member(member_id: int, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, me = ctx.need_business()
    target = await services.owned(ctx.session, Member, business.id, member_id, required=True)
    if target.role == "owner":
        raise HTTPException(403, "The owner cannot be removed")
    if target.id != me.id:  # leaving yourself is always allowed
        plans.require(me.role, "team")
        if me.role != "owner" and target.role == "admin":
            raise HTTPException(403, "Only the owner can remove admins")
    await ctx.session.delete(target)
    await ctx.session.commit()
    return {"ok": True}


# ---------------------------------------------------------------- API: stock (Team)

def product_dict(p: Product) -> dict:
    return {"id": p.id, "name": p.name, "unit": p.unit, "cost_price": q2(p.cost_price), "sale_price": q2(p.sale_price),
            "stock_qty": p.stock_qty, "archived": p.archived,
            "stock_value": q2(Decimal(p.cost_price or 0) * Decimal(p.stock_qty or 0))}


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    unit: str = Field(default="шт", max_length=16)
    cost_price: Decimal = Field(default=Decimal(0), ge=0)
    sale_price: Decimal = Field(default=Decimal(0), ge=0)
    stock_qty: Decimal = Field(default=Decimal(0))
    archived: bool = False


@api.get("/products")
async def products(ctx: Ctx = Depends(get_ctx)) -> list[dict]:
    business, member = ctx.need_business()
    plans.require(member.role, "read_own")
    plans.require_feature(business, "stock")
    rows = (await ctx.session.scalars(select(Product).where(Product.business_id == business.id).order_by(Product.name))).all()
    return [product_dict(p) for p in rows]


@api.post("/products")
async def add_product(body: ProductIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    plans.require_feature(business, "stock")
    p = Product(business_id=business.id, **body.model_dump())
    ctx.session.add(p)
    await ctx.session.commit()
    return product_dict(p)


@api.patch("/products/{product_id}")
async def edit_product(product_id: int, body: ProductIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    plans.require_feature(business, "stock")
    p = await services.owned(ctx.session, Product, business.id, product_id, required=True)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    await ctx.session.commit()
    return product_dict(p)


class RestockIn(BaseModel):
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal | None = Field(default=None, ge=0)
    record_expense: bool = True
    account_id: int | None = None


@api.post("/products/{product_id}/restock")
async def restock(product_id: int, body: RestockIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    """Goods arrived: stock goes up; optionally the purchase is recorded as an expense (cash flow).
    The cost of goods enters gross profit when the goods are sold, not here."""
    business, member = need(ctx, "write")
    plans.require_feature(business, "stock")
    p = await services.owned(ctx.session, Product, business.id, product_id, required=True)
    if body.unit_cost is not None:
        # weighted average cost
        old_qty, old_cost = Decimal(p.stock_qty or 0), Decimal(p.cost_price or 0)
        total = max(old_qty, Decimal(0)) + body.quantity
        p.cost_price = q2((max(old_qty, Decimal(0)) * old_cost + body.quantity * body.unit_cost) / total) if total else body.unit_cost
    p.stock_qty = Decimal(p.stock_qty or 0) + body.quantity
    if body.record_expense and body.unit_cost:
        cat = await services.resolve_category(ctx.session, business.id, "expense", "other_expense", "")
        await services.record_operation(ctx.session, business, member, kind="expense", amount=q2(body.quantity * body.unit_cost),
                                        category_id=cat.id if cat else None, account_id=body.account_id,
                                        note=f"Закупівля: {p.name} × {body.quantity.normalize()}")
    await ctx.session.commit()
    return product_dict(p)


# ---------------------------------------------------------------- API: referral

@api.get("/referral")
async def referral(ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "billing")
    invited = int(await ctx.session.scalar(select(func.count()).select_from(Business).where(
        Business.referred_by_business_id == business.id)) or 0)
    paid = int(await ctx.session.scalar(select(func.count()).select_from(Business).where(
        Business.referred_by_business_id == business.id, Business.referral_rewarded.is_(True))) or 0)
    link = f"https://t.me/{runtime.bot_username}?start=ref_{business.id}" if runtime.bot_username else None
    return {"link": link, "invited": invited, "paid": paid, "bonus_days": 30}
