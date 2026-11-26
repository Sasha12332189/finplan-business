"""FastAPI app: the Mini App, its API and the Telegram webhook in one service."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import handlers  # noqa: F401  registers every bot router in the right order
from . import jobs, jobs_money, runtime  # noqa: F401  (jobs_money registers its jobs)
from .api import api
from .api_money import router as money_router
from .api_ai import router as ai_router
from .team import api as team_router
from . import ai, banks
from .bot import configure_commands, dispatcher
from .config import get_settings
from .database import close_database, init_database

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
JOB_INTERVAL_SECONDS = 5 * 60

telegram_bot: Bot | None = None  # also published as app.runtime.bot
bot_username: str | None = None


def webhook_secret(bot_token: str) -> str:
    """Stable secret derived from the token, so Telegram's calls can be told apart from strangers'."""
    return hashlib.sha256(("finplan-business-webhook:" + bot_token).encode()).hexdigest()


def get_bot() -> Bot | None:
    return telegram_bot


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Start the HTTP app first; Telegram configuration must never block it."""
    global telegram_bot, bot_username
    await init_database()
    settings = get_settings()

    async def setup_telegram() -> None:
        global telegram_bot, bot_username
        if not settings.bot_token:
            logging.warning("Telegram disabled: BUSINESS_BOT_TOKEN is missing")
            return
        bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        telegram_bot = runtime.bot = bot
        try:
            bot_username = runtime.bot_username = (await bot.get_me()).username
        except Exception:
            logging.exception("getMe failed")
        if not settings.public_app_url.startswith("https://"):
            logging.warning("Telegram webhook disabled: PUBLIC_APP_URL is missing or not HTTPS")
            return
        webhook_url = settings.public_app_url.rstrip("/") + "/telegram/webhook"
        # Webhook first, so a failure in optional UI configuration cannot stop /start from working.
        try:
            await bot.set_webhook(webhook_url, secret_token=webhook_secret(settings.bot_token),
                                  allowed_updates=dispatcher.resolve_used_update_types(), drop_pending_updates=False)
            logging.info("Telegram webhook set: %s", webhook_url)
        except Exception:
            logging.exception("Failed to set Telegram webhook")
            return
        try:
            await configure_commands(bot)
        except Exception:
            logging.exception("Telegram commands/menu configuration failed; webhook remains active")

    setup = asyncio.create_task(setup_telegram())
    background = asyncio.create_task(background_jobs())
    try:
        yield
    finally:
        background.cancel()
        setup.cancel()
        if telegram_bot is not None:
            # Never delete the webhook here. On a Railway redeploy the new container sets the
            # webhook first and the old one shuts down afterwards; deleting it on shutdown
            # would leave the bot silent until the next deploy.
            try:
                await telegram_bot.session.close()
            finally:
                telegram_bot = runtime.bot = None
        await close_database()


async def background_jobs() -> None:
    await asyncio.sleep(20)  # let the webhook and bot come up first
    while True:
        try:
            await jobs.run_once(telegram_bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Background jobs failed")
        await asyncio.sleep(JOB_INTERVAL_SECONDS)


app = FastAPI(title="finplan Business", version="1.0.0", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=STATIC), name="assets")
app.include_router(api)
app.include_router(money_router)
app.include_router(ai_router)
app.include_router(team_router)
ai.install()  # weekly insights in reports
jobs.EXTRA_JOBS.append(banks.sync_job)


@app.middleware("http")
async def no_stale_mini_app(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/assets/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "bot": telegram_bot is not None}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)) -> dict:
    if telegram_bot is None:
        raise HTTPException(status_code=503, detail="Telegram bot is not configured")
    if x_telegram_bot_api_secret_token != webhook_secret(get_settings().bot_token):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    try:
        update = Update.model_validate(await request.json(), context={"bot": telegram_bot})
        await dispatcher.feed_update(telegram_bot, update)
    except Exception:
        # Answer 200 anyway: a 5xx makes Telegram retry the same update forever
        # and hold back every newer message (including /start) behind it.
        logging.exception("Failed to handle Telegram update")
    return {"ok": True}


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


# Must stay the last route. Old Menu-button / BotFather links may point at paths such as
# /app; open the Mini App for them instead of answering "Not Found".
@app.get("/{path:path}", include_in_schema=False)
async def mini_app_fallback(path: str) -> FileResponse:
    if path.startswith(("api/", "assets/", "telegram/")):
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})
