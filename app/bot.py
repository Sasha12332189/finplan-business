"""@finplan_business_bot: onboarding, quick entry, period summaries, taxes."""
from __future__ import annotations

import asyncio
import html
import logging
import os
from datetime import date

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Message, WebAppInfo,
)
from sqlalchemy import select

from . import finance, plans, services
from .config import get_settings
from .database import SessionLocal, init_database
from .finance import money
from .models import Business, Category, Counterparty, Member, Operation, User
from .texts import T

router = Router()
dispatcher = Dispatcher()
dispatcher.include_router(router)


class Onboarding(StatesGroup):
    name = State()


class LinkClient(StatesGroup):
    name = State()


def app_url() -> str:
    return get_settings().public_app_url.rstrip("/")


def app_keyboard(lang: str, path: str = "") -> InlineKeyboardMarkup | None:
    url = app_url()
    if not url.startswith("https://"):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=T(lang, "open_app"), web_app=WebAppInfo(url=url + path))]])


async def configure_commands(bot: Bot) -> None:
    commands = {
        "ru": [("start", "Начать / настройки бизнеса"), ("app", "Открыть приложение"), ("today", "Итоги дня"),
               ("week", "Итоги недели"), ("month", "Итоги месяца"), ("tax", "Налоги и сроки"),
               ("invoice", "Счёт клиенту"), ("debts", "Кто сколько должен"), ("report", "Excel / PDF отчёт"),
               ("team", "Пригласить сотрудника"), ("ai", "ИИ-ассистент"), ("premium", "Тарифы и оплата"),
               ("paysupport", "Помощь с оплатой"), ("terms", "Условия подписки")],
        "uk": [("start", "Почати / налаштування бізнесу"), ("app", "Відкрити застосунок"), ("today", "Підсумки дня"),
               ("week", "Підсумки тижня"), ("month", "Підсумки місяця"), ("tax", "Податки й терміни"),
               ("invoice", "Рахунок клієнту"), ("debts", "Хто скільки винен"), ("report", "Excel / PDF звіт"),
               ("team", "Запросити працівника"), ("ai", "ШІ-асистент"), ("premium", "Тарифи й оплата"),
               ("paysupport", "Допомога з оплатою"), ("terms", "Умови підписки")],
    }
    await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in commands["uk"]])
    await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in commands["ru"]], language_code="ru")
    url = app_url()
    if not url.startswith("https://"):
        logging.warning("PUBLIC_APP_URL is not an HTTPS URL (%r); Menu button not updated", url)
        return
    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="finplan", web_app=WebAppInfo(url=url)))


async def load(session, message_or_query) -> tuple[User, Business | None, Member | None]:
    who = message_or_query.from_user
    user = await services.ensure_user(session, who.id, who.first_name, who.username, who.language_code)
    business, member = await services.context_for(session, user)
    return user, business, member


# ---------------------------------------------------------------- onboarding

def kind_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=T(lang, "kind_fop"), callback_data="ob:kind:fop")],
        [InlineKeyboardButton(text=T(lang, "kind_freelance"), callback_data="ob:kind:freelance")],
        [InlineKeyboardButton(text=T(lang, "kind_company"), callback_data="ob:kind:company")],
    ])


def group_keyboard(lang: str, kind: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=T(lang, "group", n=n), callback_data=f"ob:group:{kind}:{n}") for n in (1, 2, 3)]]
    rows.append([InlineKeyboardButton(text=T(lang, "no_group"), callback_data=f"ob:group:{kind}:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, state: FSMContext) -> None:
    payload = (command.args or "").strip()
    async with SessionLocal() as session:
        user, business, member = await load(session, message)
        lang = user.language
        if payload.startswith("inv_"):
            from .team import accept_invite  # stage 4
            text = await accept_invite(session, user, payload[4:])
            await session.commit()
            await message.answer(text, reply_markup=app_keyboard(lang))
            return
        if payload.startswith("ref_") and payload[4:].isdigit() and business is None:
            user.pending_referral = int(payload[4:])
        await session.commit()
    url = app_url()
    if url.startswith("https://"):
        try:  # an old per-chat Menu button would override the bot-wide one
            await message.bot.set_chat_menu_button(chat_id=message.chat.id, menu_button=MenuButtonWebApp(
                text="finplan", web_app=WebAppInfo(url=url)))
        except Exception:
            logging.exception("Failed to reset the chat Menu button")
    if business is None or payload == "new":
        await state.set_state(Onboarding.name)
        await message.answer(T(lang, "welcome"))
        return
    await state.clear()
    await message.answer(T(lang, "hello_back", name=html.escape(business.name)), reply_markup=app_keyboard(lang))


@router.message(StateFilter(Onboarding.name), F.text & ~F.text.startswith("/"))
async def onboarding_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()[:120]
    await state.update_data(name=name)
    await state.set_state(None)
    async with SessionLocal() as session:
        user, _, _ = await load(session, message)
        await session.commit()
        lang = user.language
    await message.answer(T(lang, "ask_kind"), reply_markup=kind_keyboard(lang))
    # keep the name for the next steps
    await state.update_data(name=name)


@router.callback_query(F.data.startswith("ob:"))
async def onboarding_step(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    data = await state.get_data()
    name = data.get("name")
    async with SessionLocal() as session:
        user, _, _ = await load(session, callback)
        lang = user.language
        if not name:
            await session.commit()
            await callback.answer()
            await callback.message.answer(T(lang, "welcome"))
            await state.set_state(Onboarding.name)
            return
        if parts[1] == "kind":
            kind = parts[2]
            await session.commit()
            await callback.answer()
            if kind == "company":
                await finish_onboarding(callback, state, kind="company", group=None, vat=False)
            else:
                await callback.message.edit_text(T(lang, "ask_group"), reply_markup=group_keyboard(lang, kind))
            return
        if parts[1] == "group":
            kind, group = parts[2], int(parts[3])
            await session.commit()
            await callback.answer()
            if group == 3:
                await callback.message.edit_text(T(lang, "ask_vat"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=T(lang, "vat_no"), callback_data=f"ob:vat:{kind}:0")],
                    [InlineKeyboardButton(text=T(lang, "vat_yes"), callback_data=f"ob:vat:{kind}:1")]]))
            else:
                await finish_onboarding(callback, state, kind=kind, group=group or None, vat=False)
            return
        if parts[1] == "vat":
            await session.commit()
            await callback.answer()
            await finish_onboarding(callback, state, kind=parts[2], group=3, vat=parts[3] == "1")


async def finish_onboarding(callback: CallbackQuery, state: FSMContext, *, kind: str, group: int | None, vat: bool) -> None:
    data = await state.get_data()
    async with SessionLocal() as session:
        user, _, _ = await load(session, callback)
        business, _ = await services.create_business(session, user, data.get("name") or "", kind=kind,
                                                     fop_group=group, is_vat_payer=vat)
        await session.commit()
        lang, name = user.language, business.name
    await state.clear()
    await callback.message.edit_text(T(lang, "ready", name=html.escape(name)))
    keyboard = app_keyboard(lang)
    if keyboard:
        await callback.message.answer(T(lang, "tap_open"), reply_markup=keyboard)


# ---------------------------------------------------------------- commands

@router.message(Command("app"))
async def open_app(message: Message) -> None:
    async with SessionLocal() as session:
        user, _, _ = await load(session, message)
        await session.commit()
    keyboard = app_keyboard(user.language)
    await message.answer(T(user.language, "tap_open") if keyboard else T(user.language, "no_url"), reply_markup=keyboard)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    async with SessionLocal() as session:
        user, _, _ = await load(session, message)
        await session.commit()
    await message.answer(T(user.language, "help"))


def fmt_change(lang: str, pct) -> str:
    if pct is None:
        return ""
    sign = "+" if pct > 0 else ""
    return T(lang, "vs_prev", pct=f"{sign}{pct}%")


async def period_text(session, business: Business, member: Member, lang: str, period: str,
                      today: date | None = None) -> str:
    data = await services.dashboard(session, business, member, period, today)
    s, ch = data["summary"], data["change"]
    if not s["revenue"] and not s["expenses"]:
        return f"<b>{T(lang, period)}</b>\n{T(lang, 'empty_period')}"
    start, end = data["start"], data["end"]
    rng = f"{start:%d.%m}" if start == end else f"{start:%d.%m}–{end:%d.%m}"
    margin = f" · маржа {s['margin']}%" if s["margin"] is not None else ""
    text = T(lang, "summary", title=T(lang, period), range=rng, revenue=money(s["revenue"], business.currency),
             rev_change=fmt_change(lang, ch["revenue"]), expenses=money(s["expenses"], business.currency),
             exp_change=fmt_change(lang, ch["expenses"]), profit=money(s["profit"], business.currency), margin=margin)
    if s["sales_count"]:
        text += T(lang, "sales_line", count=s["sales_count"], avg=money(s["avg_check"], business.currency))
    return text


async def send_period(message: Message, period: str) -> None:
    async with SessionLocal() as session:
        user, business, member = await load(session, message)
        if business is None:
            await session.commit()
            await message.answer(T(user.language, "need_business"))
            return
        try:
            text = await period_text(session, business, member, user.language, period)
        except Exception as error:  # e.g. history limit
            from fastapi import HTTPException
            if isinstance(error, HTTPException):
                text = "Этот период доступен в Pro: /premium"
            else:
                raise
        await session.commit()
    await message.answer(text, reply_markup=app_keyboard(user.language))


@router.message(Command("today"))
async def today_cmd(message: Message) -> None:
    await send_period(message, "today")


@router.message(Command("week"))
async def week_cmd(message: Message) -> None:
    await send_period(message, "week")


@router.message(Command("month"))
async def month_cmd(message: Message) -> None:
    await send_period(message, "month")


def tax_what(lang: str, what: str) -> str:
    return T(lang, f"tax_item_{what}")


async def tax_text(session, business: Business, lang: str) -> str:
    from .tax_rates import DISCLAIMER
    overview = await services.tax_overview(session, business)
    if not overview["applicable"]:
        return T(lang, "tax_none")
    rate = f" · {overview['rate']:g}%" if business.fop_group == 3 else ""
    lines = [T(lang, "tax_title", group=business.fop_group, rate=rate)]
    for p in overview["upcoming"][:5]:
        lines.append(T(lang, "tax_line", what=tax_what(lang, p["what"]), period=p["period"],
                       amount=money(p["amount"], "UAH"), due=f"{p['due_date']:%d.%m.%Y}",
                       accruing=T(lang, "tax_accruing") if p.get("accruing") else ""))
    if len(lines) == 1:
        lines.append(T(lang, "tax_nothing"))
    decl = next((p for p in overview["upcoming"] if p.get("declaration_date") and not p.get("accruing")), None)
    if decl:
        lines.append(T(lang, "tax_declaration", period=decl["period"], date=f"{decl['declaration_date']:%d.%m.%Y}"))
    limit = overview["limit"]
    if limit:
        lines.append(T(lang, "tax_limit", year=overview["year"], used=money(limit["used"]), limit=money(limit["limit"]),
                       percent=limit["percent"]))
    lines.append(f"\n<i>{DISCLAIMER['ru' if lang == 'ru' else 'uk']}</i>")
    return "\n".join(lines)


@router.message(Command("tax"))
async def tax_cmd(message: Message) -> None:
    async with SessionLocal() as session:
        user, business, member = await load(session, message)
        if business is None:
            await session.commit()
            await message.answer(T(user.language, "need_business"))
            return
        text = await tax_text(session, business, user.language)
        await session.commit()
    await message.answer(text)


# ---------------------------------------------------------------- quick entry

def entry_keyboard(lang: str, op_id: int, kind: str) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text=T(lang, "undo"), callback_data=f"undo:{op_id}"),
           InlineKeyboardButton(text=T(lang, "change_cat"), callback_data=f"cat:{op_id}")]
    if kind == "income":
        row.append(InlineKeyboardButton(text=T(lang, "link_client"), callback_data=f"cp:{op_id}"))
    else:
        row.append(InlineKeyboardButton(text=T(lang, "link_client").replace("Клиент", "Поставщик").replace("Клієнт", "Постачальник"),
                                        callback_data=f"cp:{op_id}"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


async def entry_text(session, business: Business, lang: str, op: Operation) -> str:
    cat = await session.get(Category, op.category_id) if op.category_id else None
    cp = await session.get(Counterparty, op.counterparty_id) if op.counterparty_id else None
    head = T(lang, "saved_income" if op.kind == "income" else "saved_expense",
             amount=money(op.amount, op.currency))
    bits = [b for b in (cat.name if cat else None, cp.name if cp else None, op.note) if b]
    return head + ("\n" + html.escape(" · ".join(bits)) if bits else "")


async def save_quick_entry(message: Message, text: str, source: str = "bot") -> bool:
    parsed = finance.parse_quick_entry(text)
    if parsed is None:
        return False
    async with SessionLocal() as session:
        user, business, member = await load(session, message)
        lang = user.language
        if business is None:
            await session.commit()
            await message.answer(T(lang, "need_business"))
            return True
        if not plans.can(member.role, "add_operation"):
            await session.commit()
            await message.answer(T(lang, "not_allowed"))
            return True
        category = await services.resolve_category(session, business.id, parsed.kind, parsed.category_key, parsed.note)
        counterparty_id = None
        if parsed.counterparty:
            found = await services.find_counterparty(session, business.id, parsed.counterparty)
            if found is None:
                try:
                    found = await services.get_or_create_counterparty(session, business, parsed.counterparty)
                except Exception:
                    found = None  # over the Free limit: keep the name in the note only
            counterparty_id = found.id if found else None
        op = await services.record_operation(session, business, member, kind=parsed.kind, amount=parsed.amount,
                                             category_id=category.id if category else None,
                                             counterparty_id=counterparty_id, note=parsed.note, source=source)
        reply = await entry_text(session, business, lang, op)
        await session.commit()
        op_id, kind = op.id, op.kind
    await message.answer(reply, reply_markup=entry_keyboard(lang, op_id, kind))
    return True


async def editable_op(session, callback: CallbackQuery, op_id: int) -> tuple[User, Operation | None, Member | None]:
    user, business, member = await load(session, callback)
    if business is None:
        return user, None, None
    op = await session.get(Operation, op_id)
    if op is None or op.business_id != business.id:
        return user, None, member
    if member.role == "staff" and op.member_id != member.id:
        return user, None, member
    if not (plans.can(member.role, "write") or (member.role == "staff" and op.member_id == member.id)):
        return user, None, member
    return user, op, member


@router.callback_query(F.data.startswith("undo:"))
async def undo_entry(callback: CallbackQuery) -> None:
    op_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        user, op, _ = await editable_op(session, callback, op_id)
        if op is not None:
            await services.delete_operation(session, op)
        await session.commit()
    if op is None:
        await callback.answer(T(user.language, "gone"))
        return
    await callback.answer(T(user.language, "undone"))
    try:
        await callback.message.edit_text("<s>" + (callback.message.html_text or "") + "</s>\n" + T(user.language, "undone"))
    except Exception:
        logging.exception("Failed to mark the entry as undone")


@router.callback_query(F.data.startswith("cat:"))
async def pick_category(callback: CallbackQuery) -> None:
    op_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        user, op, _ = await editable_op(session, callback, op_id)
        cats = await services.categories(session, op.business_id, op.kind) if op else []
        await session.commit()
    if op is None:
        await callback.answer(T(user.language, "gone"))
        return
    rows, row = [], []
    for c in cats:
        row.append(InlineKeyboardButton(text=("• " if c.id == op.category_id else "") + c.name,
                                        callback_data=f"setcat:{op_id}:{c.id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("setcat:"))
async def set_category(callback: CallbackQuery) -> None:
    _, op_id, cat_id = callback.data.split(":")
    async with SessionLocal() as session:
        user, op, _ = await editable_op(session, callback, int(op_id))
        cat = await session.get(Category, int(cat_id)) if op else None
        if op is None or cat is None or cat.business_id != op.business_id or cat.kind != op.kind:
            await session.commit()
            await callback.answer(T(user.language, "gone"))
            return
        op.category_id = cat.id
        business = await session.get(Business, op.business_id)
        text = await entry_text(session, business, user.language, op)
        await session.commit()
    await callback.answer(T(user.language, "cat_set", name=cat.name))
    await callback.message.edit_text(text, reply_markup=entry_keyboard(user.language, op.id, op.kind))


@router.callback_query(F.data.startswith("cp:"))
async def pick_counterparty(callback: CallbackQuery) -> None:
    op_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        user, op, _ = await editable_op(session, callback, op_id)
        cps = list((await session.scalars(select(Counterparty).where(Counterparty.business_id == op.business_id)
                                          .order_by(Counterparty.id.desc()).limit(8))).all()) if op else []
        await session.commit()
    if op is None:
        await callback.answer(T(user.language, "gone"))
        return
    rows = [[InlineKeyboardButton(text=c.name[:30], callback_data=f"setcp:{op_id}:{c.id}")] for c in cps]
    rows.append([InlineKeyboardButton(text=T(user.language, "new_client"), callback_data=f"newcp:{op_id}")])
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("setcp:"))
async def set_counterparty(callback: CallbackQuery) -> None:
    _, op_id, cp_id = callback.data.split(":")
    async with SessionLocal() as session:
        user, op, _ = await editable_op(session, callback, int(op_id))
        cp = await session.get(Counterparty, int(cp_id)) if op else None
        if op is None or cp is None or cp.business_id != op.business_id:
            await session.commit()
            await callback.answer(T(user.language, "gone"))
            return
        op.counterparty_id = cp.id
        business = await session.get(Business, op.business_id)
        text = await entry_text(session, business, user.language, op)
        await session.commit()
    await callback.answer(T(user.language, "client_set", name=cp.name))
    await callback.message.edit_text(text, reply_markup=entry_keyboard(user.language, op.id, op.kind))


@router.callback_query(F.data.startswith("newcp:"))
async def new_counterparty(callback: CallbackQuery, state: FSMContext) -> None:
    op_id = int(callback.data.split(":")[1])
    async with SessionLocal() as session:
        user, op, _ = await editable_op(session, callback, op_id)
        await session.commit()
    if op is None:
        await callback.answer(T(user.language, "gone"))
        return
    await state.set_state(LinkClient.name)
    await state.update_data(op_id=op_id)
    await callback.answer()
    await callback.message.answer(T(user.language, "type_client"))


@router.message(StateFilter(LinkClient.name), F.text & ~F.text.startswith("/"))
async def new_counterparty_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    async with SessionLocal() as session:
        user, business, member = await load(session, message)
        op = await session.get(Operation, int(data.get("op_id") or 0))
        if business is None or op is None or op.business_id != business.id:
            await session.commit()
            return
        try:
            cp = await services.get_or_create_counterparty(session, business, message.text.strip(),
                                                           "client" if op.kind == "income" else "supplier")
        except Exception:
            await session.commit()
            await message.answer("В Free до 10 контрагентов. Больше — в Pro: /premium")
            return
        op.counterparty_id = cp.id
        text = await entry_text(session, business, user.language, op)
        await session.commit()
    await message.answer(text, reply_markup=entry_keyboard(user.language, op.id, op.kind))


# The catch-all text handler lives in its own router, included after every other module's
# router (see app/handlers.py), so commands and dialog states are handled first.
fallback_router = Router(name="fallback")


@fallback_router.message(F.text & ~F.text.startswith("/"))
async def quick_entry(message: Message) -> None:
    from . import ai, ai_bot  # questions and multi-item messages go to the AI assistant

    text = message.text or ""
    if ai.enabled() and ai_bot.wants_ai(text):
        await ai_bot.answer_free_text(message)
        return
    if await save_quick_entry(message, text):
        return
    if ai.enabled():
        await ai_bot.answer_free_text(message)
    else:
        await help_command(message)


# ---------------------------------------------------------------- entry points

async def main() -> None:
    settings = get_settings()
    if not settings.bot_token:
        raise RuntimeError("BUSINESS_BOT_TOKEN is missing")
    await init_database()
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await configure_commands(bot)
    # Polling is for local runs only. getUpdates does not work while a webhook is set,
    # so drop it here; the server sets it again on its next start.
    await bot.delete_webhook(drop_pending_updates=False)
    logging.info("finplan Business bot started (polling)")
    await dispatcher.start_polling(bot)


def run() -> None:
    """Entry point for `python -m app.bot`.

    On Railway (PORT is set) this starts the full web server: the Mini App plus the bot
    webhook, same as start_railway.py. Polling is only for local runs.
    """
    logging.basicConfig(level=logging.INFO)
    if os.getenv("PORT") or os.getenv("RAILWAY_ENVIRONMENT"):
        import uvicorn

        port = int(os.getenv("PORT", "8000"))
        logging.info("Starting finplan Business web server on 0.0.0.0:%s", port)
        uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level="info", access_log=True)
    else:
        from . import handlers  # noqa: F401  registers every module's handlers
        asyncio.run(main())


if __name__ == "__main__":
    run()
