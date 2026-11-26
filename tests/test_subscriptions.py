from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import plans

NOW = datetime(2026, 11, 26, 12, 0)


def biz(**kw):
    base = dict(owner_telegram_id=1, plan="free", plan_until=None, plan_period=None, plan_charge_id=None,
                plan_canceled=False, trial_used=False, trial_until=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_trial_gives_pro_once_for_14_days():
    b = biz()
    assert plans.effective_plan(b, NOW) == "free"
    assert plans.start_trial(b, NOW) is True
    assert plans.effective_plan(b, NOW + timedelta(days=13)) == "pro"
    assert plans.on_trial(b, NOW)
    assert plans.effective_plan(b, NOW + timedelta(days=15)) == "free"
    assert plans.start_trial(b, NOW + timedelta(days=20)) is False  # trial_used


def test_paid_plan_with_grace_period():
    b = biz(plan="team", plan_until=NOW + timedelta(days=1))
    assert plans.effective_plan(b, NOW) == "team"
    assert plans.effective_plan(b, NOW + timedelta(days=1, hours=11)) == "team"  # renewal may come late
    assert plans.effective_plan(b, NOW + timedelta(days=2)) == "free"


def test_monthly_subscription_and_renewal_keep_first_charge():
    b = biz()
    expires = int((NOW + timedelta(days=30)).timestamp())
    assert plans.apply_payment(b, "pro", "month", "ch-1", expires, is_renewal=False, now=NOW) is None
    assert b.plan == "pro" and b.plan_charge_id == "ch-1" and b.plan_period == "month"
    later = int((NOW + timedelta(days=60)).timestamp())
    plans.apply_payment(b, "pro", "month", "ch-2", later, is_renewal=True, now=NOW + timedelta(days=30))
    assert b.plan_charge_id == "ch-1"  # Telegram identifies the subscription by the first charge
    assert b.plan_until == datetime.utcfromtimestamp(later)


def test_switching_plan_cancels_previous_subscription():
    b = biz()
    plans.apply_payment(b, "pro", "month", "ch-1", int((NOW + timedelta(days=30)).timestamp()), False, now=NOW)
    old = plans.apply_payment(b, "team", "month", "ch-9", int((NOW + timedelta(days=31)).timestamp()), False,
                              now=NOW + timedelta(days=1))
    assert old == "ch-1" and b.plan == "team" and b.plan_charge_id == "ch-9"


def test_yearly_payment_extends_from_current_end_and_stops_monthly_renewal():
    b = biz()
    plans.apply_payment(b, "pro", "month", "ch-1", int((NOW + timedelta(days=30)).timestamp()), False, now=NOW)
    end_of_month = b.plan_until
    old = plans.apply_payment(b, "pro", "year", "ch-y", None, False, now=NOW + timedelta(days=5))
    assert old == "ch-1"
    assert b.plan_until == end_of_month + timedelta(days=365)
    assert b.plan_charge_id is None and b.plan_period == "year"


def test_payload_roundtrip_and_validation():
    p = plans.invoice_payload("team", "year", 12, 345)
    assert plans.parse_payload(p) == ("team", "year", 12, 345)
    assert plans.parse_payload("biz:gold:month:1:2") is None
    assert plans.parse_payload("sub:pro:1") is None
    assert plans.price_of("pro", "month") == 399 and plans.price_of("team", "year") == 7999


def test_limits_and_upgrade_errors():
    free = biz()
    assert plans.limits_for(free)["ai_requests"] == 10
    with pytest.raises(HTTPException) as e:
        plans.check_count(free, "counterparties", 10)
    assert e.value.status_code == 402 and e.value.detail["plan_needed"] == "pro"
    plans.check_count(free, "counterparties", 9)
    with pytest.raises(HTTPException) as e:
        plans.require_feature(free, "stock")
    assert e.value.detail["plan_needed"] == "team"
    pro = biz(plan="pro", plan_until=datetime.utcnow() + timedelta(days=3))
    with pytest.raises(HTTPException) as e:
        plans.require_feature(pro, "stock")
    assert e.value.detail["plan_needed"] == "team"
    assert plans.plan_needed("roles", "accountant") == "pro"
    assert plans.plan_needed("roles", "staff") == "team"


def test_history_window_for_free():
    free = biz()
    today = date(2026, 11, 26)
    assert plans.history_start(free, today) == date(2026, 10, 1)
    plans.check_history(free, date(2026, 10, 1), today)
    with pytest.raises(HTTPException):
        plans.check_history(free, date(2026, 9, 30), today)
    assert plans.history_start(biz(plan="pro", plan_until=datetime.utcnow() + timedelta(days=1)), today) is None


def test_roles():
    assert plans.can("owner", "billing") and not plans.can("admin", "billing")
    assert plans.can("staff", "add_operation") and not plans.can("staff", "read")
    assert plans.can("accountant", "export") and not plans.can("accountant", "add_operation")
    assert plans.can("staff", "read_own") and plans.can("accountant", "read_own")


def test_admin_owner_always_team(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "admin_telegram_ids", "1")
    assert plans.effective_plan(biz(), NOW) == "team"
