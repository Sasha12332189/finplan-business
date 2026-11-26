"""Collects the bot's routers in the order Telegram updates must be matched:
commands and dialog states first, the free-text quick entry last."""
from __future__ import annotations

import importlib
import logging

from .bot import dispatcher, fallback_router

_MODULES = ("payments_bot", "reports_bot", "documents_bot", "ai_bot", "team")

for _name in _MODULES:
    try:
        _module = importlib.import_module(f"app.{_name}")
    except ModuleNotFoundError as error:
        if error.name != f"app.{_name}":
            raise
        continue
    router = getattr(_module, "router", None)
    if router is not None:
        dispatcher.include_router(router)
        logging.debug("Bot router %s included", _name)

dispatcher.include_router(fallback_router)
