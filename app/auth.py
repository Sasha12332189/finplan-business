"""Telegram Mini App authentication. The Telegram id always comes from signed initData,
never from the client; the business and the role are looked up on the server."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import AsyncIterator, Optional
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import SessionLocal
from .models import Business, Member, User
from .services import context_for, ensure_user


@dataclass(frozen=True)
class TelegramIdentity:
    telegram_id: int
    first_name: str
    username: Optional[str]
    language_code: Optional[str] = None


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int) -> TelegramIdentity:
    """Validate Telegram Mini App initData as specified by Telegram's Web Apps docs."""
    if not init_data or not bot_token:
        raise ValueError("Telegram Mini App authentication is not configured")
    values = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = values.pop("hash", None)
    auth_date = values.get("auth_date")
    if not received_hash or not auth_date or not values.get("user"):
        raise ValueError("Missing Telegram Mini App authentication fields")
    if abs(time.time() - int(auth_date)) > max_age_seconds:
        raise ValueError("Telegram Mini App session has expired")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError("Telegram Mini App signature is invalid")

    telegram_user = json.loads(values["user"])
    return TelegramIdentity(
        telegram_id=int(telegram_user["id"]),
        first_name=telegram_user.get("first_name") or "",
        username=telegram_user.get("username"),
        language_code=telegram_user.get("language_code"),
    )


def identity_from_headers(init_data: str | None, dev_user: str | None) -> TelegramIdentity:
    settings = get_settings()
    try:
        if init_data:
            return validate_init_data(init_data, settings.bot_token, settings.webapp_auth_max_age_seconds)
        if settings.debug and (dev_user or settings.dev_telegram_user_id):
            return TelegramIdentity(telegram_id=int(dev_user or settings.dev_telegram_user_id),
                                    first_name="Developer", username=None, language_code="ru")
        raise ValueError("Open finplan Business from its Telegram bot")
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@dataclass
class Ctx:
    session: AsyncSession
    user: User
    business: Business | None
    member: Member | None

    @property
    def role(self) -> str:
        return self.member.role if self.member else ""

    def need_business(self) -> tuple[Business, Member]:
        if self.business is None or self.member is None:
            raise HTTPException(status_code=409, detail={"code": "onboarding", "message": "Create a business first"})
        from . import plans
        # After a downgrade, members whose role the plan no longer includes lose access until it is renewed.
        if self.member.role != "owner" and self.member.role not in plans.limits_for(self.business)["roles"]:
            raise plans.upgrade_error(self.business, "roles", value=self.member.role)
        return self.business, self.member


async def get_ctx(
    session: AsyncSession = Depends(db_session),
    x_telegram_init_data: str | None = Header(default=None),
    x_dev_telegram_user: str | None = Header(default=None),
    x_business_id: str | None = Header(default=None),
) -> Ctx:
    identity = identity_from_headers(x_telegram_init_data, x_dev_telegram_user)
    user = await ensure_user(session, identity.telegram_id, identity.first_name, identity.username,
                             identity.language_code)
    business_id = int(x_business_id) if x_business_id and x_business_id.isdigit() else None
    business, member = await context_for(session, user, business_id)
    if member and identity.first_name and member.name != identity.first_name:
        member.name = identity.first_name
    await session.commit()
    return Ctx(session=session, user=user, business=business, member=member)
