"""Telegram Stars payments: /premium, /terms, /paysupport, pre-checkout, successful payments
(including monthly renewals), refunds by the bot admin, referral reward."""
from __future__ import annotations

import html
import logging
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy import select

from . import plans, services
from .bot import app_keyboard, load
from .config import get_settings
from .database import SessionLocal
from .models import Business, Member, Payment, utcnow

router = Router(name="payments")
REFERRAL_BONUS = timedelta(days=30)

PLAN_NAMES = {"pro": "finplan Business Pro", "team": "finplan Business Team"}


def premium_text(lang: str) -> str:
    p = plans.PRICES
    if lang == "ru":
        return ("<b>Тарифы finplan Business</b>\n\n"
                f"<b>Pro</b> — {p['pro']['month']} ⭐ в месяц или {p['pro']['year']} ⭐ в год\n"
                "Вся история, Excel и PDF отчёты (и авто 1-го числа), ИИ-ассистент 300 запросов, фото чеков и голос, "
                "импорт monobank, прогноз и кассовый разрыв, счета без лимита с PDF, + бухгалтер.\n\n"
                f"<b>Team</b> — {p['team']['month']} ⭐ в месяц или {p['team']['year']} ⭐ в год\n"
                "Всё из Pro, команда до 10 человек с ролями, склад, ИИ 1000 запросов.\n\n"
                "Месячная подписка продлевается каждые 30 дней, отменить можно в любой момент. "
                "Свои записи вы видите и выгружаете всегда, даже в Free.")
    return ("<b>Тарифи finplan Business</b>\n\n"
            f"<b>Pro</b> — {p['pro']['month']} ⭐ на місяць або {p['pro']['year']} ⭐ на рік\n"
            "Уся історія, Excel і PDF звіти (і авто 1-го числа), ШІ-асистент 300 запитів, фото чеків і голос, "
            "імпорт monobank, прогноз і касовий розрив, рахунки без ліміту з PDF, + бухгалтер.\n\n"
            f"<b>Team</b> — {p['team']['month']} ⭐ на місяць або {p['team']['year']} ⭐ на рік\n"
            "Усе з Pro, команда до 10 людей з ролями, склад, ШІ 1000 запитів.\n\n"
            "Місячна підписка продовжується кожні 30 днів, скасувати можна будь-коли. "
            "Свої записи ви бачите й вивантажуєте завжди, навіть у Free.")


async def invoice_links(bot: Bot, business_id: int, telegram_id: int) -> list[list[InlineKeyboardButton]]:
    rows = []
    for plan in ("pro", "team"):
        title, description = plans.TITLES[plan]
        for period in ("month", "year"):
            stars = plans.price_of(plan, period)
            extra = {"subscription_period": plans.SUBSCRIPTION_PERIOD} if period == "month" else {}
            label = f"{plan.title()} · {'30' if period == 'month' else '365'}"
            link = await bot.create_invoice_link(
                title=f"{title} · {'місяць' if period == 'month' else 'рік'}"[:32], description=description[:255],
                payload=plans.invoice_payload(plan, period, business_id, telegram_id), currency="XTR",
                prices=[LabeledPrice(label=label, amount=stars)], **extra)
            rows.append(InlineKeyboardButton(text=f"{plan.title()} — {stars} ⭐ / {'міс' if period == 'month' else 'рік'}", url=link))
    return [rows[0:2], rows[2:4]]


@router.message(Command("premium"))
async def premium(message: Message) -> None:
    async with SessionLocal() as session:
        user, business, member = await load(session, message)
        await session.commit()
    lang = user.language
    if business is None:
        await message.answer("/start")
        return
    status = plans.status(business)
    head = ""
    if status["paid_plan"]:
        head = (f"Сейчас: <b>{PLAN_NAMES[status['paid_plan']]}</b> до {status['until']:%d.%m.%Y}.\n\n" if lang == "ru" else
                f"Зараз: <b>{PLAN_NAMES[status['paid_plan']]}</b> до {status['until']:%d.%m.%Y}.\n\n")
    elif status["trial"]:
        head = (f"Пробный Pro до {status['trial_until']:%d.%m.%Y}.\n\n" if lang == "ru" else
                f"Пробний Pro до {status['trial_until']:%d.%m.%Y}.\n\n")
    if not plans.can(member.role, "billing"):
        await message.answer(head + ("Подписку оформляет владелец бизнеса." if lang == "ru" else "Підписку оформлює власник бізнесу."))
        return
    try:
        rows = await invoice_links(message.bot, business.id, message.from_user.id)
    except Exception:
        logging.exception("Failed to create invoice links")
        await message.answer(head + premium_text(lang) + "\n\nОплата сейчас недоступна, попробуйте позже.")
        return
    await message.answer(head + premium_text(lang), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    """Telegram asks to confirm within 10 seconds before charging Stars."""
    parsed = plans.parse_payload(query.invoice_payload)
    ok = parsed is not None and query.currency == "XTR" and parsed[3] == query.from_user.id \
        and query.total_amount == plans.price_of(parsed[0], parsed[1])
    if ok:
        async with SessionLocal() as session:
            member = await session.scalar(select(Member).where(Member.business_id == parsed[2],
                                                               Member.telegram_id == query.from_user.id))
            ok = member is not None and plans.can(member.role, "billing")
    if not ok:
        await query.answer(ok=False, error_message="Этот счёт устарел. Откройте оплату заново: /premium")
        return
    await query.answer(ok=True)


async def reward_referrer(session, business: Business) -> int | None:
    """The business that invited this one gets 30 days of Pro after its first payment."""
    if not business.referred_by_business_id or business.referral_rewarded:
        return None
    referrer = await session.get(Business, business.referred_by_business_id)
    business.referral_rewarded = True
    if referrer is None:
        return None
    now = utcnow()
    if referrer.plan in plans.PRICES and referrer.plan_until and referrer.plan_until > now:
        referrer.plan_until = referrer.plan_until + REFERRAL_BONUS
    else:
        referrer.trial_until = max(referrer.trial_until or now, now) + REFERRAL_BONUS
    return referrer.owner_telegram_id


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    payment = message.successful_payment
    parsed = plans.parse_payload(payment.invoice_payload)
    if parsed is None or payment.currency != "XTR":
        logging.warning("Unexpected payment payload %r", payment.invoice_payload)
        return
    plan, period, business_id, _ = parsed
    is_renewal = bool(payment.is_recurring and not payment.is_first_recurring)
    async with SessionLocal() as session:
        user, _, _ = await load(session, message)
        business = await session.get(Business, business_id)
        if business is None:
            logging.error("Payment for a missing business %s: %s", business_id, payment.telegram_payment_charge_id)
            await session.commit()
            return
        if await session.scalar(select(Payment).where(Payment.telegram_charge_id == payment.telegram_payment_charge_id)):
            await session.commit()
            return  # the same update delivered twice
        previous_charge = plans.apply_payment(business, plan, period, payment.telegram_payment_charge_id,
                                              payment.subscription_expiration_date, is_renewal)
        session.add(Payment(business_id=business.id, telegram_id=message.from_user.id,
                            telegram_charge_id=payment.telegram_payment_charge_id, plan=plan, stars=payment.total_amount,
                            period=period, is_recurring=is_renewal, expires_at=business.plan_until))
        referrer_chat = await reward_referrer(session, business)
        await session.commit()
        until, lang, name = business.plan_until, user.language, business.name
    if previous_charge:
        # Switched plan or to a yearly payment: stop the old subscription from renewing.
        try:
            await message.bot.edit_user_star_subscription(user_id=message.from_user.id,
                                                          telegram_payment_charge_id=previous_charge, is_canceled=True)
        except Exception:
            logging.exception("Failed to cancel the previous subscription")
    if is_renewal:
        await message.answer(f"{PLAN_NAMES[plan]} продлён до {until:%d.%m.%Y}. Спасибо!" if lang == "ru" else
                             f"{PLAN_NAMES[plan]} продовжено до {until:%d.%m.%Y}. Дякуємо!")
        return
    features = ("• отчёты Excel и PDF: /report\n• ИИ-ассистент: просто задайте вопрос\n• фото чеков и голосовые\n"
                "• импорт monobank и прогноз — в приложении\n" + ("• команда и склад: /team\n" if plan == "team" else ""))
    if lang != "ru":
        features = ("• звіти Excel і PDF: /report\n• ШІ-асистент: просто поставте питання\n• фото чеків і голосові\n"
                    "• імпорт monobank і прогноз — у застосунку\n" + ("• команда й склад: /team\n" if plan == "team" else ""))
    head = (f"Готово! <b>{PLAN_NAMES[plan]}</b> для «{html.escape(name)}» включён до {until:%d.%m.%Y}.\n\nТеперь доступно:\n"
            if lang == "ru" else
            f"Готово! <b>{PLAN_NAMES[plan]}</b> для «{html.escape(name)}» увімкнено до {until:%d.%m.%Y}.\n\nТепер доступно:\n")
    await message.answer(head + features, reply_markup=app_keyboard(lang))
    if referrer_chat:
        try:
            await message.bot.send_message(referrer_chat, "Ваш друг оплатил finplan Business — вам +30 дней Pro. Спасибо!")
        except Exception:
            logging.exception("Failed to notify the referrer")


@router.message(Command("paysupport"))
async def paysupport(message: Message) -> None:
    contact = get_settings().support_contact.strip()
    where = f"Напишите {html.escape(contact)}" if contact else "Свяжитесь с владельцем бота (контакт в описании бота)"
    await message.answer(
        "<b>Помощь с оплатой</b>\n"
        f"{where} — укажите дату платежа и что пошло не так. Если подписка не включилась после оплаты, "
        "мы проверим платёж и включим её или вернём звёзды.\n\n"
        "Отменить автопродление: приложение → Ещё → подписка, или Telegram → Настройки → Мои звёзды.")


@router.message(Command("terms"))
async def terms(message: Message) -> None:
    p = plans.PRICES
    await message.answer(
        "<b>Условия подписки finplan Business</b>\n"
        f"• Pro — {p['pro']['month']} ⭐ за 30 дней или {p['pro']['year']} ⭐ за 365 дней; "
        f"Team — {p['team']['month']} ⭐ / {p['team']['year']} ⭐. Оплата через Telegram Stars.\n"
        "• Месячная подписка продлевается автоматически каждые 30 дней, пока вы её не отмените. Годовая — разовый платёж.\n"
        "• После отмены доступ сохраняется до конца оплаченного периода.\n"
        "• Каждый новый бизнес получает 14 дней Pro бесплатно один раз.\n"
        "• Ваши данные не удаляются: после окончания подписки записи остаются, их можно смотреть и выгружать в CSV.\n"
        "• Расчёт налогов справочный и не заменяет бухгалтера.\n"
        "Вопросы по оплате: /paysupport")


@router.message(Command("refund"))
async def refund(message: Message, command: CommandObject) -> None:
    """/refund <telegram_payment_charge_id> — bot admins only (ADMIN_TELEGRAM_IDS)."""
    if message.from_user.id not in get_settings().admin_ids:
        return
    charge = (command.args or "").strip()
    async with SessionLocal() as session:
        payment = await session.scalar(select(Payment).where(Payment.telegram_charge_id == charge))
        if payment is None:
            await message.answer("Платёж не найден.")
            return
        try:
            await message.bot.refund_star_payment(user_id=payment.telegram_id, telegram_payment_charge_id=charge)
        except Exception as error:
            await message.answer(f"Telegram отказал: {html.escape(str(error))}")
            return
        payment.refunded = True
        business = await session.get(Business, payment.business_id)
        if business and business.plan == payment.plan:
            business.plan_until = utcnow()
            business.plan_canceled = True
        await session.commit()
    await message.answer("Звёзды возвращены, подписка отключена.")


__all__ = ["router", "services"]
