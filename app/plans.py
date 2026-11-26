"""Plans, limits and roles (spec sections 9 and 11). Every check here runs on the server.

Payments use Telegram Stars (currency "XTR"): a native 30-day Stars subscription for the
monthly plan (Telegram renews it and sends a new successful_payment), and a one-off payment
for a year.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

from .config import get_settings
from .finance import shift_month

SUBSCRIPTION_PERIOD = 30 * 24 * 60 * 60  # the only period Telegram allows for Stars subscriptions
YEAR = timedelta(days=365)
TRIAL = timedelta(days=14)
GRACE = timedelta(hours=12)  # renewals can arrive a little after the period ends

PRICES = {
    "pro": {"month": 399, "year": 3499},
    "team": {"month": 899, "year": 7999},
}
RANK = {"free": 0, "pro": 1, "team": 2}

UNLIMITED = None
LIMITS = {
    # history_months: how many months back analytics can open (current + previous = 1).
    "free": {"history_months": 1, "invoices_per_month": 5, "counterparties": 10, "projects": 1,
             "reports": False, "ai_requests": 10, "media": False, "banks": False, "forecast": False,
             "members": 1, "roles": ("owner",), "stock": False, "auto_report": False, "invoice_pdf": False},
    "pro": {"history_months": UNLIMITED, "invoices_per_month": UNLIMITED, "counterparties": UNLIMITED,
            "projects": UNLIMITED, "reports": True, "ai_requests": 300, "media": True, "banks": True,
            "forecast": True, "members": 2, "roles": ("owner", "accountant"), "stock": False,
            "auto_report": True, "invoice_pdf": True},
    "team": {"history_months": UNLIMITED, "invoices_per_month": UNLIMITED, "counterparties": UNLIMITED,
             "projects": UNLIMITED, "reports": True, "ai_requests": 1000, "media": True, "banks": True,
             "forecast": True, "members": 10, "roles": ("owner", "admin", "staff", "accountant"),
             "stock": True, "auto_report": True, "invoice_pdf": True},
}

TITLES = {
    "pro": ("finplan Business Pro", "Вся история, Excel и PDF отчёты, ИИ-ассистент, фото чеков и голос, "
                                    "импорт monobank, прогноз и кассовый разрыв, бухгалтер в доступе."),
    "team": ("finplan Business Team", "Всё из Pro, команда до 10 человек с ролями, склад и 1000 запросов к ИИ."),
}

# ---------------------------------------------------------------- roles

ROLES = ("owner", "admin", "staff", "accountant")
# What each role may do. staff: only adds operations; accountant: only reads and exports.
PERMISSIONS = {
    "owner": {"read", "write", "add_operation", "export", "manage", "billing", "team"},
    "admin": {"read", "write", "add_operation", "export", "manage", "team"},
    "staff": {"add_operation", "read_own"},
    "accountant": {"read", "export"},
}


def can(role: str, action: str) -> bool:
    perms = PERMISSIONS.get(role, set())
    if action == "read_own":
        return bool(perms & {"read", "read_own"})
    return action in perms


def require(role: str, action: str) -> None:
    if not can(role, action):
        raise HTTPException(status_code=403, detail={"code": "forbidden", "action": action, "role": role,
                                                     "message": "Your role does not allow this."})


# ---------------------------------------------------------------- plan state

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def effective_plan(business, now: datetime | None = None) -> str:
    now = now or utcnow()
    if business.owner_telegram_id in get_settings().admin_ids:
        return "team"
    until = as_naive_utc(business.plan_until)
    if business.plan in PRICES and until and until + GRACE > now:
        return business.plan
    trial = as_naive_utc(business.trial_until)
    if trial and trial > now:
        return "pro"
    return "free"


def on_trial(business, now: datetime | None = None) -> bool:
    now = now or utcnow()
    paid = business.plan in PRICES and business.plan_until and as_naive_utc(business.plan_until) + GRACE > now
    return not paid and bool(business.trial_until and as_naive_utc(business.trial_until) > now) \
        and business.owner_telegram_id not in get_settings().admin_ids


def start_trial(business, now: datetime | None = None) -> bool:
    if business.trial_used:
        return False
    business.trial_used = True
    business.trial_until = (now or utcnow()) + TRIAL
    return True


def limits_for(business) -> dict:
    return LIMITS[effective_plan(business)]


def plan_needed(feature: str, value=True) -> str:
    """The cheapest plan that allows a feature (or a role in "roles")."""
    for plan in ("pro", "team"):
        limit = LIMITS[plan][feature]
        if feature == "roles":
            if value in limit:
                return plan
        elif limit != LIMITS["free"][feature]:
            return plan
    return "team"


def upgrade_error(business, feature: str, limit=None, value=True) -> HTTPException:
    current = effective_plan(business)
    needed = plan_needed(feature, value)
    if RANK[needed] <= RANK[current]:
        needed = "team"
    return HTTPException(status_code=402, detail={
        "code": "plan_required", "feature": feature, "limit": limit, "plan": current, "plan_needed": needed,
        "message": f"Available in {needed.title()}.",
    })


def require_feature(business, feature: str) -> None:
    if not limits_for(business)[feature]:
        raise upgrade_error(business, feature)


def check_count(business, feature: str, used: int) -> None:
    limit = limits_for(business)[feature]
    if limit is not None and used >= limit:
        raise upgrade_error(business, feature, limit)


def history_start(business, today: date) -> date | None:
    """The first date analytics may show, None = all history."""
    months = limits_for(business)["history_months"]
    if months is None:
        return None
    y, m = shift_month(today.year, today.month, -months)
    return date(y, m, 1)


def check_history(business, start: date, today: date) -> None:
    first = history_start(business, today)
    if first and start < first:
        raise upgrade_error(business, "history_months", limits_for(business)["history_months"])


def status(business, now: datetime | None = None) -> dict:
    now = now or utcnow()
    plan = effective_plan(business, now)
    paid = business.plan in PRICES and business.plan_until and as_naive_utc(business.plan_until) + GRACE > now
    return {
        "plan": plan,
        "paid_plan": business.plan if paid else None,
        "period": business.plan_period if paid else None,
        "until": as_naive_utc(business.plan_until) if paid else None,
        "trial": on_trial(business, now),
        "trial_until": as_naive_utc(business.trial_until) if on_trial(business, now) else None,
        "trial_available": not business.trial_used,
        "is_admin": business.owner_telegram_id in get_settings().admin_ids,
        "auto_renew": bool(paid and business.plan_period == "month" and business.plan_charge_id and not business.plan_canceled),
        "can_manage": bool(paid and business.plan_period == "month" and business.plan_charge_id),
        "limits": {k: (list(v) if isinstance(v, tuple) else v) for k, v in LIMITS[plan].items()},
        "prices": PRICES,
        "plans": {p: {k: (list(v) if isinstance(v, tuple) else v) for k, v in LIMITS[p].items()} for p in LIMITS},
    }


# ---------------------------------------------------------------- payments

def invoice_payload(plan: str, period: str, business_id: int, telegram_id: int) -> str:
    return f"biz:{plan}:{period}:{business_id}:{telegram_id}"


def parse_payload(payload: str) -> tuple[str, str, int, int] | None:
    """"biz:pro:month:12:345" -> (plan, period, business id, Telegram user id)."""
    parts = (payload or "").split(":")
    if len(parts) != 5 or parts[0] != "biz" or parts[1] not in PRICES or parts[2] not in ("month", "year"):
        return None
    try:
        return parts[1], parts[2], int(parts[3]), int(parts[4])
    except ValueError:
        return None


def price_of(plan: str, period: str) -> int:
    return PRICES[plan][period]


def apply_payment(business, plan: str, period: str, charge_id: str, expires_unix: int | None,
                  is_renewal: bool, now: datetime | None = None) -> str | None:
    """Activate or extend a plan. Returns the charge id of an older subscription that must stop
    renewing (when the business switched plans), else None. The caller records the Payment
    row and makes sure the same charge id is not applied twice."""
    now = now or utcnow()
    current_until = as_naive_utc(business.plan_until)
    active = effective_plan(business, now) in PRICES and business.plan in PRICES and current_until \
        and current_until + GRACE > now
    same_plan = business.plan == plan and active
    previous_charge = None
    if active and business.plan_period == "month" and business.plan_charge_id \
            and business.plan_charge_id != charge_id and (period == "year" or business.plan != plan):
        previous_charge = business.plan_charge_id  # switched plan or to a year: stop the old renewal
    if period == "month":
        expires = datetime.fromtimestamp(expires_unix, timezone.utc).replace(tzinfo=None) if expires_unix \
            else now + timedelta(seconds=SUBSCRIPTION_PERIOD)
        # A renewal keeps the first charge id: Telegram identifies the subscription by it.
        if not (is_renewal and same_plan and business.plan_charge_id):
            business.plan_charge_id = charge_id
        business.plan_until = max(expires, current_until) if same_plan and current_until else expires
    else:
        base = current_until if same_plan and current_until and current_until > now else now
        business.plan_until = base + YEAR
        business.plan_charge_id = None  # a one-off payment: nothing renews
    business.plan = plan
    business.plan_period = period
    business.plan_canceled = False
    return previous_charge


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"
