"""Pure business calculations (spec section 6): periods, profit, taxes, limits, forecast,
quick-entry parsing. No database access here, so everything is easy to test.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable
from zoneinfo import ZoneInfo

from . import tax_rates

ZERO = Decimal("0")
CENT = Decimal("0.01")


def q2(value) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def local_today(tz: str = "Europe/Kyiv", now: datetime | None = None) -> date:
    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = ZoneInfo("Europe/Kyiv")
    return (now.astimezone(zone) if now else datetime.now(zone)).date()


def local_now(tz: str = "Europe/Kyiv") -> datetime:
    try:
        return datetime.now(ZoneInfo(tz))
    except Exception:
        return datetime.now(ZoneInfo("Europe/Kyiv"))


# ---------------------------------------------------------------- periods

PERIODS = ("today", "week", "month", "quarter", "year")


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def quarter_of(day: date) -> int:
    return (day.month - 1) // 3 + 1


def quarter_range(year: int, quarter: int) -> tuple[date, date]:
    start = date(year, 3 * (quarter - 1) + 1, 1)
    end_month = 3 * quarter
    return start, date(year, end_month, calendar.monthrange(year, end_month)[1])


def period_range(kind: str, today: date, offset: int = 0) -> tuple[date, date]:
    """Inclusive date range of a period; offset -1 = the previous one."""
    if kind == "today":
        day = today + timedelta(days=offset)
        return day, day
    if kind == "week":
        monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        return monday, monday + timedelta(days=6)
    if kind == "month":
        y, m = shift_month(today.year, today.month, offset)
        return month_range(y, m)
    if kind == "quarter":
        index = today.year * 4 + quarter_of(today) - 1 + offset
        return quarter_range(index // 4, index % 4 + 1)
    if kind == "year":
        return date(today.year + offset, 1, 1), date(today.year + offset, 12, 31)
    raise ValueError(f"Unknown period {kind!r}")


def previous_comparable(kind: str, today: date) -> tuple[date, date]:
    """The previous period cut to the same length as the elapsed part of the current one,
    so "this month so far" is compared with "last month up to the same day"."""
    start, end = period_range(kind, today, 0)
    prev_start, prev_end = period_range(kind, today, -1)
    elapsed = (min(today, end) - start).days
    return prev_start, min(prev_end, prev_start + timedelta(days=elapsed))


def parse_period_key(key: str) -> tuple[date, date]:
    """'2026-11', '2026-Q4', '2026', '2026-11-01..2026-11-15'."""
    key = (key or "").strip()
    if ".." in key:
        a, b = key.split("..", 1)
        start, end = date.fromisoformat(a), date.fromisoformat(b)
        if end < start:
            raise ValueError("Period end is before start")
        return start, end
    m = re.fullmatch(r"(\d{4})-Q([1-4])", key, re.I)
    if m:
        return quarter_range(int(m.group(1)), int(m.group(2)))
    m = re.fullmatch(r"(\d{4})-(\d{2})", key)
    if m:
        return month_range(int(m.group(1)), int(m.group(2)))
    if re.fullmatch(r"\d{4}", key):
        return date(int(key), 1, 1), date(int(key), 12, 31)
    raise ValueError(f"Unknown period {key!r}")


def days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# ---------------------------------------------------------------- profit

@dataclass
class Op:
    """The part of an operation the calculations need."""
    kind: str
    amount: Decimal
    occurred_at: date
    is_cogs: bool = False
    cogs_amount: Decimal | None = None
    category_id: int | None = None
    counterparty_id: int | None = None
    project_id: int | None = None
    member_id: int | None = None


@dataclass
class Summary:
    revenue: Decimal = ZERO
    expenses: Decimal = ZERO
    cogs: Decimal = ZERO
    sales_count: int = 0
    clients: set = field(default_factory=set)

    @property
    def profit(self) -> Decimal:
        return q2(self.revenue - self.expenses)

    @property
    def gross_profit(self) -> Decimal:
        return q2(self.revenue - self.cogs)

    @property
    def margin(self) -> Decimal | None:
        """Profit / revenue, percent. None when there is no revenue."""
        if self.revenue <= 0:
            return None
        return (self.profit / self.revenue * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    @property
    def avg_check(self) -> Decimal | None:
        return q2(self.revenue / self.sales_count) if self.sales_count else None

    @property
    def revenue_per_client(self) -> Decimal | None:
        return q2(self.revenue / len(self.clients)) if self.clients else None

    def as_dict(self) -> dict:
        return {
            "revenue": q2(self.revenue), "expenses": q2(self.expenses), "profit": self.profit,
            "cogs": q2(self.cogs), "gross_profit": self.gross_profit, "margin": self.margin,
            "sales_count": self.sales_count, "avg_check": self.avg_check,
            "clients": len(self.clients), "revenue_per_client": self.revenue_per_client,
        }


def summarize(ops: Iterable[Op]) -> Summary:
    """Profit = income − expenses; transfers between accounts are ignored.
    Gross profit = income − cost of goods (expenses in is_cogs categories + cost of products sold)."""
    s = Summary()
    for op in ops:
        amount = Decimal(op.amount or 0)
        if op.kind == "income":
            s.revenue += amount
            s.sales_count += 1
            if op.counterparty_id:
                s.clients.add(op.counterparty_id)
            if op.cogs_amount:
                s.cogs += Decimal(op.cogs_amount)
        elif op.kind == "expense":
            s.expenses += amount
            if op.is_cogs:
                s.cogs += amount
    # Cost of products sold is not a cash expense of the period (the purchase was), but it
    # belongs to the P&L: count it in expenses only through gross profit.
    return s


def pct_change(current: Decimal, previous: Decimal) -> Decimal | None:
    if not previous:
        return None
    return ((Decimal(current) - Decimal(previous)) / abs(Decimal(previous)) * 100).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP)


def group_totals(ops: Iterable[Op], key: str) -> dict:
    """{key value: {"income": x, "expense": y}} for key in category_id/counterparty_id/project_id/member_id."""
    out: dict = {}
    for op in ops:
        if op.kind not in ("income", "expense"):
            continue
        k = getattr(op, key)
        row = out.setdefault(k, {"income": ZERO, "expense": ZERO, "count": 0})
        row[op.kind] += Decimal(op.amount)
        row["count"] += 1
    return out


def daily_series(ops: Iterable[Op], start: date, end: date) -> list[dict]:
    by_day = {d: {"date": d, "income": ZERO, "expense": ZERO} for d in days(start, end)}
    for op in ops:
        if op.occurred_at in by_day and op.kind in ("income", "expense"):
            by_day[op.occurred_at][op.kind] += Decimal(op.amount)
    return list(by_day.values())


def monthly_series(ops: Iterable[Op], start: date, end: date) -> list[dict]:
    months: dict[str, dict] = {}
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months[f"{y:04d}-{m:02d}"] = {"month": f"{y:04d}-{m:02d}", "income": ZERO, "expense": ZERO}
        y, m = shift_month(y, m, 1)
    for op in ops:
        k = f"{op.occurred_at.year:04d}-{op.occurred_at.month:02d}"
        if k in months and op.kind in ("income", "expense"):
            months[k][op.kind] += Decimal(op.amount)
    for row in months.values():
        row["net"] = q2(row["income"] - row["expense"])
    return list(months.values())


# ---------------------------------------------------------------- taxes

@dataclass
class TaxProfile:
    kind: str = "fop"
    fop_group: int | None = 3
    tax_rate: Decimal = Decimal("5")  # percent, group 3
    is_vat_payer: bool = False
    pays_esv: bool = True

    @property
    def is_fop(self) -> bool:
        return self.fop_group in (1, 2, 3)


def default_group3_rate(is_vat_payer: bool, year: int | None = None) -> Decimal:
    rates, _ = tax_rates.rates_for(year or date.today().year)
    return rates["group3_rate"]["vat" if is_vat_payer else "no_vat"]


def quarter_taxes(profile: TaxProfile, year: int, quarter: int, income: Decimal) -> dict:
    """Single tax, ESV and military levy of a quarter plus the deadlines."""
    rates, exact = tax_rates.rates_for(year)
    start, end = quarter_range(year, quarter)
    income = Decimal(income or 0)
    single = esv = levy = ZERO
    if profile.fop_group == 3:
        single = q2(income * Decimal(profile.tax_rate) / 100)
        levy = q2(income * rates["military_levy_group3_rate"] / 100)
        due = end + timedelta(days=tax_rates.DEADLINES["group3_payment_days"])
        declaration = end + timedelta(days=tax_rates.DEADLINES["group3_declaration_days"])
    elif profile.fop_group in (1, 2):
        single = q2(rates["single_tax_month"][profile.fop_group] * 3)
        levy = q2(rates["military_levy_month"] * 3)
        # Paid monthly in advance; the quarter is settled with the last month's payment.
        due = date(end.year, end.month, tax_rates.DEADLINES["group12_monthly_day"])
        declaration = date(end.year + 1, 3, 1) if quarter == 4 else None  # yearly declaration
    else:
        return {"period": f"{year}-Q{quarter}", "applicable": False}
    if profile.pays_esv:
        esv = q2(rates["esv_month"] * 3)
    ey, em = shift_month(end.year, end.month, 1)
    esv_due = date(ey, em, tax_rates.DEADLINES["esv_quarter_day"])
    return {
        "period": f"{year}-Q{quarter}", "applicable": True, "year": year, "quarter": quarter,
        "income_total": q2(income), "single_tax": single, "esv": esv, "military_levy": levy,
        "total": q2(single + esv + levy), "due_date": due, "esv_due_date": esv_due,
        "declaration_date": declaration, "rates_exact": exact,
    }


def monthly_payments(profile: TaxProfile, year: int, month: int) -> list[dict]:
    """Groups 1–2: what is due by the 20th of a month."""
    if profile.fop_group not in (1, 2):
        return []
    rates, _ = tax_rates.rates_for(year)
    due = date(year, month, tax_rates.DEADLINES["group12_monthly_day"])
    return [
        {"what": "single_tax", "amount": q2(rates["single_tax_month"][profile.fop_group]), "due_date": due},
        {"what": "military_levy", "amount": q2(rates["military_levy_month"]), "due_date": due},
    ]


def upcoming_payments(profile: TaxProfile, today: date, quarter_income: dict[tuple[int, int], Decimal],
                      paid_periods: set[str] = frozenset()) -> list[dict]:
    """Tax payments due from today on, nearest first.

    quarter_income maps (year, quarter) to income; the current and the previous quarter matter."""
    if not profile.is_fop:
        return []
    out: list[dict] = []
    q = quarter_of(today)
    candidates = [(today.year, q)]
    py, pq = (today.year - 1, 4) if q == 1 else (today.year, q - 1)
    candidates.insert(0, (py, pq))
    for y, qq in candidates:
        period = f"{y}-Q{qq}"
        t = quarter_taxes(profile, y, qq, quarter_income.get((y, qq), ZERO))
        if period in paid_periods:
            continue
        if profile.fop_group == 3 and t["due_date"] >= today and (y, qq) != (today.year, q):
            out.append({"what": "single_tax", "period": period, "amount": t["single_tax"] + t["military_levy"],
                        "due_date": t["due_date"], "declaration_date": t["declaration_date"]})
        if profile.fop_group == 3 and (y, qq) == (today.year, q):
            # The current quarter is not over: show what has accrued so far.
            out.append({"what": "single_tax", "period": period, "amount": t["single_tax"] + t["military_levy"],
                        "due_date": t["due_date"], "declaration_date": t["declaration_date"], "accruing": True})
        if profile.pays_esv and t["esv_due_date"] >= today and t["esv"]:
            out.append({"what": "esv", "period": period, "amount": t["esv"], "due_date": t["esv_due_date"]})
    if profile.fop_group in (1, 2):
        day = tax_rates.DEADLINES["group12_monthly_day"]
        y, m = (today.year, today.month) if today.day <= day else shift_month(today.year, today.month, 1)
        for p in monthly_payments(profile, y, m):
            out.append({**p, "period": f"{y:04d}-{m:02d}"})
    out.sort(key=lambda p: (p["due_date"], p["what"]))
    return out


def income_limit(profile: TaxProfile, year: int, income_ytd: Decimal) -> dict | None:
    if not profile.is_fop:
        return None
    rates, exact = tax_rates.rates_for(year)
    limit = rates["income_limit"][profile.fop_group]
    used = Decimal(income_ytd or 0)
    percent = (used / limit * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if limit else ZERO
    level = None
    for threshold in tax_rates.LIMIT_WARNINGS:
        if percent >= threshold:
            level = threshold
    return {"limit": limit, "used": q2(used), "left": q2(max(limit - used, ZERO)), "percent": percent,
            "level": level, "rates_exact": exact}


# ---------------------------------------------------------------- forecast

def forecast_month_end(revenue_so_far: Decimal, today: date) -> Decimal:
    """Revenue at the end of the month at the current daily pace."""
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    return q2(Decimal(revenue_so_far or 0) / today.day * days_in_month)


def next_occurrence(day_of_month: int, after: date) -> date:
    """The first date >= after that falls on day_of_month (clamped to short months)."""
    y, m = after.year, after.month
    for _ in range(3):
        d = date(y, m, min(day_of_month, calendar.monthrange(y, m)[1]))
        if d >= after:
            return d
        y, m = shift_month(y, m, 1)
    raise AssertionError("unreachable")


def cash_gap(balance: Decimal, today: date, recurring: Iterable[dict], horizon_days: int = 45) -> dict | None:
    """Walk through scheduled payments (dicts with kind, amount, day_of_month, note) and find the
    first one the money on the accounts does not cover."""
    events = []
    end = today + timedelta(days=horizon_days)
    for r in recurring:
        d = next_occurrence(int(r["day_of_month"]), today)
        while d <= end:
            events.append((d, r))
            y, m = shift_month(d.year, d.month, 1)
            d = date(y, m, min(int(r["day_of_month"]), calendar.monthrange(y, m)[1]))
    events.sort(key=lambda e: (e[0], 0 if e[1]["kind"] == "income" else 1))
    running = Decimal(balance or 0)
    for d, r in events:
        amount = Decimal(r["amount"])
        if r["kind"] == "income":
            running += amount
            continue
        if running < amount:
            return {"date": d, "amount": q2(amount), "note": r.get("note") or "", "balance": q2(running),
                    "shortfall": q2(amount - running)}
        running -= amount
    return None


# ---------------------------------------------------------------- quick entry

# Words that point to a default category (by its key). Stems, lower case, ru + uk.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sales": ("прода", "продал", "продаж", "продав", "выручк", "виручк", "касса", "каса", "заказ", "замовл", "торт", "чек"),
    "services": ("услуг", "послуг", "работ", "робот", "консульт", "дизайн", "логотип", "сайт", "smm", "ремонт", "стрижк", "маникюр", "манікюр"),
    "prepayment": ("предоплат", "передоплат", "аванс", "завдаток", "задаток"),
    "goods": ("закуп", "товар", "оптов", "постачальн", "поставщ", "накладн"),
    "materials": ("мука", "муки", "борошн", "сахар", "цукор", "яйц", "масл", "молок", "сыр", "сир", "материал", "матеріал", "ткан", "тканин", "сырь", "сировин", "фурнитур", "фурнітур", "краск", "фарб"),
    "packaging": ("упаков", "пакет", "коробк", "короб", "стакан", "этикет", "етикет"),
    "rent": ("аренд", "оренд", "помещени", "приміщен"),
    "salary": ("зарплат", "зп", "аванс сотр", "премия", "премі", "оплата сотр", "оплата працівн"),
    "ads": ("реклам", "таргет", "instagram", "инстаграм", "інстаграм", "facebook", "promo", "промо", "блогер"),
    "delivery": ("доставк", "нова пошта", "новая почта", "новой почт", "нп ", "укрпошт", "такси", "таксі", "бензин", "пальне", "топлив"),
    "services_it": ("интернет", "інтернет", "связь", "зв'яз", "звяз", "телефон", "подписк", "підписк", "хостинг", "домен", "сервис", "сервіс", "crm", "програм"),
    "taxes": ("налог", "податок", "податк", "есв", "єсв", "единый", "єдиний"),
    "bank": ("комисс", "коміс", "банк", "эквайр", "еквайр"),
}

INCOME_WORDS = ("прода", "продал", "продаж", "продав", "получил", "отримав", "оплатил клиент", "оплата от", "оплата від",
                "выручк", "виручк", "предоплат", "передоплат", "аванс от", "заказ", "замовл", "доход", "дохід")
EXPENSE_WORDS = ("купил", "купила", "купив", "купила", "заплатил", "заплатила", "заплатив", "оплатил", "оплатила",
                 "оплатив", "потратил", "витратив", "расход", "витрат")

INCOME_KEYS = {"sales", "services", "prepayment", "other_income"}

_NUMBER = r"\d+(?:[ \u00a0]\d{3})*(?:[.,]\d{1,2})?(?:\s*(?:тыс|тис|к|k)\b)?"


def parse_amount(raw: str) -> Decimal | None:
    raw = raw.strip().lower().replace("\u00a0", " ")
    mult = Decimal(1)
    for suffix in ("тыс", "тис", "к", "k"):
        if raw.endswith(suffix):
            raw, mult = raw[: -len(suffix)].strip(), Decimal(1000)
            break
    raw = raw.replace(" ", "").replace(",", ".")
    try:
        value = Decimal(raw) * mult
    except Exception:
        return None
    return q2(value) if value > 0 else None


@dataclass
class QuickEntry:
    kind: str
    amount: Decimal
    note: str
    category_key: str | None
    counterparty: str | None = None
    quantity: Decimal | None = None
    explicit_sign: bool = False


def category_key_for(text: str) -> str | None:
    low = " " + text.lower() + " "
    best, best_pos = None, None
    for key, words in CATEGORY_KEYWORDS.items():
        for w in words:
            pos = low.find(w)
            if pos >= 0 and (best_pos is None or pos < best_pos):
                best, best_pos = key, pos
    return best


def parse_quick_entry(text: str) -> QuickEntry | None:
    """`4500 продажа торт`, `-1200 мука`, `+15000 Иванов предоплата`, `продал 3 торта по 450`,
    `купил мешок муки за 900`. Returns None when the message holds no amount."""
    text = (text or "").strip()
    if not text or text.startswith("/") or len(text) > 300:
        return None
    sign = None
    m = re.match(rf"^\s*([+\-−])?\s*({_NUMBER})(?:\s*(?:грн|₴|uah))?(?:\s+(.*))?$", text, re.I | re.S)
    quantity = None
    per = re.search(rf"(\d+(?:[.,]\d+)?)\s+[^\d]*?\s*по\s+({_NUMBER})", text, re.I)
    if per:
        m = None
    if m and parse_amount(m.group(2)) is not None:
        sign = {"+": "income", "-": "expense", "−": "expense"}.get(m.group(1) or "")
        amount = parse_amount(m.group(2))
        note = (m.group(3) or "").strip()
    else:
        # "продал 3 торта по 450" -> 1350; "купил муку за 900" -> 900
        if per:
            quantity = Decimal(per.group(1).replace(",", "."))
            price = parse_amount(per.group(2))
            if price is None:
                return None
            amount = q2(quantity * price)
        else:
            found = re.search(rf"(?:за|на|:)?\s*({_NUMBER})(?:\s*(?:грн|₴|uah))?\s*$", text, re.I) or \
                re.search(rf"({_NUMBER})", text, re.I)
            if not found:
                return None
            amount = parse_amount(found.group(1))
            if amount is None:
                return None
            text = (text[: found.start()] + " " + text[found.end():]).strip()
        note = text
    if amount is None:
        return None
    note = re.sub(r"\s+", " ", note).strip(" ,.;")
    low = note.lower()
    key = category_key_for(note)
    if sign:
        kind = sign
    elif any(w in low for w in EXPENSE_WORDS):
        kind = "expense"
    elif any(w in low for w in INCOME_WORDS) or key in INCOME_KEYS:
        kind = "income"
    else:
        kind = "expense"
    if kind == "income" and key not in INCOME_KEYS:
        key = "prepayment" if key == "prepayment" else ("sales" if key in (None, "goods", "materials") else key)
        if key not in INCOME_KEYS:
            key = "sales"
    if kind == "expense" and key in INCOME_KEYS:
        key = None
    counterparty = None
    if kind == "income" and note:
        first = note.split()[0]
        if first[:1].isupper() and category_key_for(first) is None and not any(w in first.lower() for w in INCOME_WORDS):
            counterparty = first.strip(",.")
    return QuickEntry(kind=kind, amount=amount, note=note[:200], category_key=key, counterparty=counterparty,
                      quantity=quantity, explicit_sign=bool(sign))


# ---------------------------------------------------------------- formatting

CURRENCY_SIGNS = {"UAH": "₴", "USD": "$", "EUR": "€", "PLN": "zł", "GBP": "£"}


def money(value, currency: str = "UAH", sign: bool = False) -> str:
    v = q2(value)
    text = f"{abs(v):,.2f}".replace(",", " ").replace(".00", "")
    prefix = ("+" if v > 0 else "−" if v < 0 else "") if sign else ("−" if v < 0 else "")
    return f"{prefix}{text} {CURRENCY_SIGNS.get(currency, currency)}"
