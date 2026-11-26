"""Bank import (spec section 10): monobank personal API and PrivatBank Autoclient.

Tokens are encrypted with ENCRYPTION_KEY (Fernet) and never leave the server.
Imported operations have source="bank" and are de-duplicated by bank_tx_id.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from . import finance, services
from .config import get_settings
from .models import Account, BankConnection, Business, Operation, utcnow

MONO = "https://api.monobank.ua"
PRIVAT = "https://acp.privatbank.ua/api"
MONO_MAX_RANGE = timedelta(days=31)  # the bank's limit for one statement request
MONO_MIN_INTERVAL = timedelta(seconds=61)  # one statement call per minute per token
ISO_CURRENCY = {980: "UAH", 840: "USD", 978: "EUR", 985: "PLN", 826: "GBP"}


# ---------------------------------------------------------------- encryption

def _fernet():
    from cryptography.fernet import Fernet

    raw = get_settings().encryption_key
    if not raw:
        raise HTTPException(503, "ENCRYPTION_KEY is not set on the server, bank connections are disabled")
    try:
        return Fernet(raw.encode())
    except ValueError:
        # Any passphrase works: it is stretched into a valid Fernet key.
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


class BankError(Exception):
    pass


# ---------------------------------------------------------------- monobank

async def mono_get(token: str, path: str) -> object:
    async with httpx.AsyncClient(timeout=20) as http:
        response = await http.get(MONO + path, headers={"X-Token": token})
    if response.status_code == 429:
        raise BankError("monobank: too many requests, try again in a minute")
    if response.status_code in (401, 403):
        raise BankError("monobank: the token is invalid or revoked")
    if response.status_code >= 400:
        raise BankError(f"monobank: HTTP {response.status_code}")
    return response.json()


async def mono_accounts(token: str) -> list[dict]:
    info = await mono_get(token, "/personal/client-info")
    out = []
    for a in info.get("accounts", []):
        out.append({"id": a["id"], "type": a.get("type"), "currency": ISO_CURRENCY.get(a.get("currencyCode"), str(a.get("currencyCode"))),
                    "masked": (a.get("maskedPan") or [a.get("iban", "")])[0] if a.get("maskedPan") else a.get("iban", ""),
                    "iban": a.get("iban"), "balance": Decimal(a.get("balance", 0)) / 100, "is_fop": a.get("type") == "fop"})
    out.sort(key=lambda a: (not a["is_fop"], a["currency"] != "UAH"))
    return out


def mono_to_operation(tx: dict) -> dict:
    """Map one statement item (amounts are in minor units, signed) to operation fields."""
    amount = Decimal(int(tx["amount"])) / 100
    when = datetime.fromtimestamp(int(tx["time"]), timezone.utc)
    note = " · ".join(filter(None, [tx.get("description"), tx.get("comment")]))[:500]
    return {"bank_tx_id": f"mono:{tx['id']}", "kind": "income" if amount > 0 else "expense", "amount": abs(amount),
            "currency": ISO_CURRENCY.get(int(tx.get("currencyCode", 980)), "UAH"), "when": when, "note": note,
            "counterparty": tx.get("counterName") or None}


# ---------------------------------------------------------------- PrivatBank Autoclient (unverified with a live account)

async def privat_transactions(client_id: str, token: str, iban: str, start: date) -> list[dict]:
    headers = {"id": client_id, "token": token, "Content-Type": "application/json;charset=utf8", "User-Agent": "finplan-business"}
    out, follow_id = [], None
    async with httpx.AsyncClient(timeout=30) as http:
        for _ in range(20):
            params = {"acc": iban, "startDate": start.strftime("%d-%m-%Y"), "limit": 100}
            if follow_id:
                params["followId"] = follow_id
            response = await http.get(f"{PRIVAT}/statements/transactions", headers=headers, params=params)
            if response.status_code in (401, 403):
                raise BankError("PrivatBank: id/token are invalid")
            if response.status_code >= 400:
                raise BankError(f"PrivatBank: HTTP {response.status_code}")
            data = response.json()
            out.extend(data.get("transactions") or [])
            if not data.get("exist_next_page"):
                break
            follow_id = data.get("next_page_id")
    return out


def privat_to_operation(tx: dict) -> dict:
    amount = Decimal(str(tx.get("SUM", "0")).replace(",", "."))
    kind = "income" if tx.get("TRANTYPE") == "C" else "expense"
    day = datetime.strptime(tx.get("DAT_OD") or tx.get("DATE_TIME_DAT_OD_TIM_P", "")[:10], "%d.%m.%Y")
    ident = tx.get("ID") or tx.get("REF", "") + str(tx.get("REFN", ""))
    return {"bank_tx_id": f"privat:{ident}", "kind": kind, "amount": abs(amount), "currency": tx.get("CCY") or "UAH",
            "when": day.replace(tzinfo=timezone.utc), "note": (tx.get("OSND") or "")[:500],
            "counterparty": tx.get("AUT_CNTR_NAM") or None}


# ---------------------------------------------------------------- import

async def import_items(session, business: Business, conn: BankConnection, items: list[dict]) -> int:
    if not items:
        return 0
    ids = [i["bank_tx_id"] for i in items]
    existing = set((await session.scalars(select(Operation.bank_tx_id).where(Operation.bank_tx_id.in_(ids)))).all())
    created = 0
    for item in sorted(items, key=lambda i: i["when"]):
        if item["bank_tx_id"] in existing or item["amount"] <= 0:
            continue
        kind = item["kind"]
        key = finance.category_key_for(item["note"])
        if kind == "income" and key not in finance.INCOME_KEYS:
            key = "sales"
        cat = await services.resolve_category(session, business.id, kind, key, item["note"])
        cp = await services.find_counterparty(session, business.id, item["counterparty"]) if item["counterparty"] else None
        day = item["when"].astimezone(finance.ZoneInfo(business.timezone)).date()
        try:
            await services.record_operation(session, business, None, kind=kind, amount=item["amount"],
                                            currency=item["currency"], category_id=cat.id if cat else None,
                                            counterparty_id=cp.id if cp else None, account_id=conn.account_id,
                                            note=item["note"] or item["counterparty"], occurred_at=day, source="bank",
                                            bank_tx_id=item["bank_tx_id"])
            created += 1
            existing.add(item["bank_tx_id"])
        except HTTPException as error:
            logging.warning("Skipped bank item %s: %s", item["bank_tx_id"], error.detail)
    return created


async def sync(session, business: Business, conn: BankConnection, *, manual: bool = False) -> int:
    now = utcnow()
    if conn.bank == "mono" and conn.last_sync_at and now - conn.last_sync_at < MONO_MIN_INTERVAL:
        if manual:
            raise HTTPException(429, "monobank allows one update per minute, try again shortly")
        return 0
    start = conn.last_sync_at - timedelta(hours=2) if conn.last_sync_at else now - timedelta(days=30)
    start = max(start, now - MONO_MAX_RANGE + timedelta(minutes=5))
    try:
        token = decrypt(conn.token_encrypted)
        if conn.bank == "mono":
            frm, to = int(start.replace(tzinfo=timezone.utc).timestamp()), int(now.replace(tzinfo=timezone.utc).timestamp())
            raw = await mono_get(token, f"/personal/statement/{conn.account_external_id}/{frm}/{to}")
            items = [mono_to_operation(tx) for tx in raw or []]
        else:
            raw = await privat_transactions(decrypt(conn.client_id_encrypted or ""), token, conn.account_external_id,
                                            start.date())
            items = [privat_to_operation(tx) for tx in raw]
        created = await import_items(session, business, conn, items)
        conn.last_sync_at, conn.last_error = now, None
        return created
    except BankError as error:
        conn.last_error = str(error)[:300]
        conn.last_sync_at = now  # back off until the next interval
        if manual:
            raise HTTPException(502, str(error)) from error
        return 0
    except Exception as error:
        logging.exception("Bank sync failed for connection %s", conn.id)
        conn.last_error = "Unexpected error"
        if manual:
            raise HTTPException(502, "The bank did not answer, try later") from error
        return 0


async def ensure_account(session, business: Business, bank: str, label: str, account_id: int | None) -> int:
    if account_id:
        acc = await services.owned(session, Account, business.id, account_id, required=True)
        acc.bank = bank
        return acc.id
    acc = Account(business_id=business.id, name=label[:80], bank=bank)
    session.add(acc)
    await session.flush()
    return acc.id


def connection_dict(c: BankConnection) -> dict:
    return {"id": c.id, "bank": c.bank, "account_label": c.account_label, "account_id": c.account_id,
            "last_sync_at": c.last_sync_at, "last_error": c.last_error}


async def sync_job(session, bot, business: Business, lang: str, now) -> None:
    from . import plans
    if not plans.limits_for(business)["banks"]:
        return
    interval = timedelta(minutes=max(get_settings().bank_sync_minutes, 2))
    conns = (await session.scalars(select(BankConnection).where(BankConnection.business_id == business.id))).all()
    for conn in conns:
        if conn.last_sync_at and utcnow() - conn.last_sync_at < interval:
            continue
        await sync(session, business, conn)
