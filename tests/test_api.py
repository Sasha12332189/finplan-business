from datetime import timedelta

from conftest import as_user

OWNER = 1001


async def make_business(client, tg=OWNER, **kw):
    body = {"name": "Торти Олі", "kind": "fop", "fop_group": 3, **kw}
    r = await client.post("/api/business", json=body, headers=as_user(tg))
    assert r.status_code == 200, r.text
    return r.json()


async def test_requires_telegram_auth(client):
    r = await client.get("/api/me")
    assert r.status_code == 401


async def test_onboarding_creates_defaults_and_trial(client):
    r = await client.get("/api/me", headers=as_user(OWNER))
    assert r.json()["business"] is None
    b = await make_business(client)
    assert b["role"] == "owner" and float(b["tax_rate"]) == 5
    me = (await client.get("/api/me", headers=as_user(OWNER))).json()
    assert me["plan"]["plan"] == "pro" and me["plan"]["trial"] is True
    meta = (await client.get("/api/meta", headers=as_user(OWNER))).json()
    assert {c["key"] for c in meta["categories"]} >= {"sales", "materials", "rent"}
    assert len(meta["accounts"]) == 2


async def test_operations_dashboard_and_balance(client):
    await make_business(client)
    meta = (await client.get("/api/meta", headers=as_user(OWNER))).json()
    sales = next(c["id"] for c in meta["categories"] if c["key"] == "sales")
    materials = next(c["id"] for c in meta["categories"] if c["key"] == "materials")
    cash, card = meta["accounts"][0]["id"], meta["accounts"][1]["id"]
    h = as_user(OWNER)
    assert (await client.post("/api/operations", json={"kind": "income", "amount": "4500", "category_id": sales,
                                                       "account_id": card}, headers=h)).status_code == 200
    assert (await client.post("/api/operations", json={"kind": "expense", "amount": "1200", "category_id": materials,
                                                       "account_id": card}, headers=h)).status_code == 200
    assert (await client.post("/api/operations", json={"kind": "transfer", "amount": "1000", "account_id": card,
                                                       "to_account_id": cash}, headers=h)).status_code == 200
    # wrong category kind is rejected
    r = await client.post("/api/operations", json={"kind": "expense", "amount": "1", "category_id": sales}, headers=h)
    assert r.status_code == 422
    d = (await client.get("/api/dashboard?period=month", headers=h)).json()
    s = d["summary"]
    assert float(s["revenue"]) == 4500 and float(s["expenses"]) == 1200 and float(s["profit"]) == 3300
    assert float(s["gross_profit"]) == 3300  # materials are cost of goods
    assert float(d["balance"]) == 3300
    balances = {a["id"]: float(a["balance"]) for a in d["accounts"]}
    assert balances == {cash: 1000, card: 2300}
    assert d["tax"]["applicable"] and d["tax"]["limit"]["used"]


async def test_edit_and_delete_operation(client):
    await make_business(client)
    h = as_user(OWNER)
    op = (await client.post("/api/operations", json={"kind": "income", "amount": "100"}, headers=h)).json()
    r = await client.patch(f"/api/operations/{op['id']}", json={"kind": "income", "amount": "250", "note": "ok"}, headers=h)
    assert r.status_code == 200 and float(r.json()["amount"]) == 250 and r.json()["id"] == op["id"]
    items = (await client.get("/api/operations", headers=h)).json()["items"]
    assert len(items) == 1 and items[0]["note"] == "ok"
    assert (await client.delete(f"/api/operations/{op['id']}", headers=h)).status_code == 200
    assert (await client.get("/api/operations", headers=h)).json()["items"] == []


async def test_other_people_cannot_see_a_business(client):
    b = await make_business(client)
    r = await client.get("/api/dashboard", headers=as_user(2002, b["id"]))
    assert r.status_code == 403


async def test_free_plan_history_limit(client):
    b = await make_business(client)
    from app.database import SessionLocal
    from app.models import Business, utcnow
    async with SessionLocal() as s:
        row = await s.get(Business, b["id"])
        row.trial_until = utcnow() - timedelta(days=1)  # trial is over
        await s.commit()
    h = as_user(OWNER)
    assert (await client.get("/api/dashboard?period=month", headers=h)).status_code == 200
    r = await client.get("/api/dashboard?period=year", headers=h)
    assert r.status_code == 402 and r.json()["detail"]["plan_needed"] == "pro"


async def test_tax_endpoint_and_paid_flag(client):
    await make_business(client)
    h = as_user(OWNER)
    await client.post("/api/operations", json={"kind": "income", "amount": "10000"}, headers=h)
    d = (await client.get("/api/tax", headers=h)).json()
    current = next(q for q in d["quarters"] if not q.get("future") and float(q["income_total"]) > 0)
    assert float(current["single_tax"]) == 500
    r = await client.post(f"/api/tax/{current['period']}/paid", json={"paid": True}, headers=h)
    assert r.json()["status"] == "paid"
    d = (await client.get("/api/tax", headers=h)).json()
    assert next(q for q in d["quarters"] if q["period"] == current["period"])["status"] == "paid"


async def test_spa_fallback_and_health(client):
    assert (await client.get("/health")).json()["ok"] is True
    r = await client.get("/some/old/path")
    assert r.status_code == 200 and "finplan Business" in r.text
    assert (await client.get("/api/nothing")).status_code == 404
