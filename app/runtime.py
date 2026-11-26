"""Process-wide handles set at startup (the Telegram bot), so API modules can send messages
without importing app.main."""
from __future__ import annotations

from aiogram import Bot

bot: Bot | None = None
bot_username: str | None = None


def require_bot() -> Bot:
    from fastapi import HTTPException

    if bot is None:
        raise HTTPException(503, "The Telegram bot is not configured on the server")
    return bot
