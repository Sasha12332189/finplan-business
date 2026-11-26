from datetime import timedelta
from decimal import Decimal

import pytest
from conftest import as_user

OWNER, STAFF, ACC = 7001, 7002, 7003


async def setup(client, plan="team"):
    h = as_user(OWNER)
    b = (await client.post("/api/business", json={"name": "Кав'ярня", "kind": "fop", "fop_group": 2}, headers=h)).json()
    from app import runtime
    from app.database import SessionLocal
    from app.models import Business, utcnow
    runtime.bot_username = "finplan_business_bot"
    async with SessionLocal() as s:
        row = await s.get(Business, b["id"])
        if plan == "free":
            row.trial_until = utcnow() - timedelta(days=1)
        else:
            row.plan, row.plan_until, row.plan_period = plan, utcnow() + timedelta(days=30), "month"
        await s.commit()
    return b, h


async def join(token: str, telegram_id: int, name: str):
    from app.database import SessionLocal
    from app.services import ensure_user
    from app.team import accept_invite
    async with SessionLocal() as s:
        user = await ensure_user(s, telegram_id, name, None, "uk")
        text = await accept_invite(s, user, token)
        await s.commit()
        return text


async def test_invite_is_one_time_and_roles_are_enforced(client):
    b, h = await setup(client)
    inv = (await client.post("/api/team/invites", json={"role": "staff"}, headers=h)).json()
    assert inv["link"].startswith("https://t.me/finplan_business_bot?start=inv_")
    token = inv["link"].split("inv_", 1)[1]
    assert "Ласкаво просимо" in await join(token, STAFF, "Іра")
    assert "недійсне" in await join(token, 9999, "Чужий")  # one-time
    hs = as_user(STAFF, b["id"])
    # staff adds operations but cannot read the dashboard numbers of others or manage anything
    mine = (await client.post("/api/operations", json={"kind": "income", "amount": "100"}, headers=hs)).json()
    await client.post("/api/operations", json={"kind": "income", "amount": "900"}, headers=h)
    items = (await client.get("/api/operations", headers=hs)).json()["items"]
    assert [i["id"] for i in items] == [mine["id"]]
    assert (await client.get("/api/tax", headers=hs)).status_code == 403
    assert (await client.post("/api/categories", json={"name": "x", "kind": "income"}, headers=hs)).status_code == 403
    assert (await client.post("/api/team/invites", json={"role": "staff"}, headers=hs)).status_code == 403
    d = (await client.get("/api/dashboard?period=month", headers=hs)).json()
    assert float(d["summary"]["revenue"]) == 100 and "balance" not in d


async def test_accountant_reads_but_cannot_write(client):
    b, h = await setup(client)
    inv = (await client.post("/api/team/invites", json={"role": "accountant"}, headers=h)).json()
    await join(inv["link"].split("inv_", 1)[1], ACC, "Бух")
    ha = as_user(ACC, b["id"])
    assert (await client.get("/api/tax", headers=ha)).status_code == 200
    assert (await client.get("/api/reports?period=month", headers=ha)).status_code == 200
    assert (await client.post("/api/operations", json={"kind": "income", "amount": "1"}, headers=ha)).status_code == 403
    assert (await client.post("/api/invoices", json={"items": [{"name": "x", "qty": 1, "price": 1}]}, headers=ha)).status_code == 403


async def test_plan_limits_for_team(client):
    b, h = await setup(client, plan="pro")
    # Pro: only one accountant, no staff
    assert (await client.post("/api/team/invites", json={"role": "staff"}, headers=h)).status_code == 402
    assert (await client.post("/api/team/invites", json={"role": "accountant"}, headers=h)).status_code == 200
    assert (await client.post("/api/team/invites", json={"role": "accountant"}, headers=h)).status_code == 402


async def test_member_loses_access_after_downgrade(client):
    b, h = await setup(client)
    inv = (await client.post("/api/team/invites", json={"role": "staff"}, headers=h)).json()
    await join(inv["link"].split("inv_", 1)[1], STAFF, "Іра")
    from app.database import SessionLocal
    from app.models import Business, utcnow
    async with SessionLocal() as s:
        row = await s.get(Business, b["id"])
        row.plan_until = utcnow() - timedelta(days=2)
        row.trial_until = None
        await s.commit()
    r = await client.get("/api/operations", headers=as_user(STAFF, b["id"]))
    assert r.status_code == 402 and r.json()["detail"]["plan_needed"] == "team"
    assert (await client.get("/api/operations", headers=h)).status_code == 200  # the owner keeps their data


async def test_stock_sale_lowers_stock_and_feeds_gross_profit(client):
    b, h = await setup(client)
    p = (await client.post("/api/products", json={"name": "Капучино", "cost_price": "20", "sale_price": "65",
                                                   "stock_qty": "10"}, headers=h)).json()
    await client.post(f"/api/products/{p['id']}/restock", json={"quantity": "10", "unit_cost": "30"}, headers=h)
    prod = (await client.get("/api/products", headers=h)).json()[0]
    assert Decimal(str(prod["stock_qty"])) == 20 and float(prod["cost_price"]) == 25  # weighted average
    sale = (await client.post("/api/operations", json={"kind": "income", "amount": "130", "product_id": p["id"],
                                                        "quantity": "2"}, headers=h)).json()
    assert float(sale["cogs_amount"]) == 50
    prod = (await client.get("/api/products", headers=h)).json()[0]
    assert Decimal(str(prod["stock_qty"])) == 18
    rep = (await client.get("/api/reports?period=month", headers=h)).json()
    assert float(rep["pnl"]["gross_profit"]) == 80  # 130 - 2 × 25
    await client.delete(f"/api/operations/{sale['id']}", headers=h)
    assert Decimal(str((await client.get("/api/products", headers=h)).json()[0]["stock_qty"])) == 20


async def test_stock_and_referral_gates(client):
    b, h = await setup(client, plan="pro")
    assert (await client.get("/api/products", headers=h)).status_code == 402
    ref = (await client.get("/api/referral", headers=h)).json()
    assert ref["link"] == f"https://t.me/finplan_business_bot?start=ref_{b['id']}"


async def test_referral_reward_on_first_payment(client):
    b, h = await setup(client, plan="free")
    from app.database import SessionLocal
    from app.models import Business, User, utcnow
    from app.payments_bot import reward_referrer
    from app.services import create_business, ensure_user
    async with SessionLocal() as s:
        friend = await ensure_user(s, 8008, "Друг", None, "uk")
        friend.pending_referral = b["id"]
        fb, _ = await create_business(s, friend, "Друг ФОП")
        assert fb.referred_by_business_id == b["id"]
        assert await reward_referrer(s, fb) == OWNER
        assert await reward_referrer(s, fb) is None  # only once
        await s.commit()
        ref = await s.get(Business, b["id"])
        assert ref.trial_until > utcnow() + timedelta(days=29)
