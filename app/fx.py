"""Exchange rates from the National Bank of Ukraine (official, free, no key), cached for an hour."""
from __future__ import annotations

import time
from datetime import date
from decimal import Decimal

import httpx

NBU_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json"
_cache: dict[str, tuple[float, dict[str, Decimal]]] = {}


class RateUnavailable(Exception):
    pass


async def uah_rates(day: date | None = None) -> dict[str, Decimal]:
    """{"USD": UAH per 1 USD, …}"""
    key = (day or date.today()).isoformat()
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < 3600:
        return cached[1]
    params = {"date": day.strftime("%Y%m%d")} if day else None
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(NBU_URL, params=params)
            response.raise_for_status()
            rows = response.json()
    except Exception as error:
        raise RateUnavailable(str(error)) from error
    rates = {row["cc"].upper(): Decimal(str(row["rate"])) for row in rows if row.get("cc") and row.get("rate")}
    rates["UAH"] = Decimal(1)
    _cache[key] = (time.time(), rates)
    return rates


async def convert(amount: Decimal, currency: str, base: str, day: date | None = None) -> Decimal:
    currency, base = currency.upper(), base.upper()
    if currency == base:
        return Decimal(amount)
    rates = await uah_rates(day)
    if currency not in rates or base not in rates:
        raise RateUnavailable(f"No NBU rate for {currency}/{base}")
    return (Decimal(amount) * rates[currency] / rates[base]).quantize(Decimal("0.01"))
