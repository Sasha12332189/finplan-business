"""AI assistant with a scripted fake Claude client (no network), and bank import."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import as_user
from sqlalchemy import func, select

OWNER = 5005


def block_text(text):
    return SimpleNamespace(type="text", text=text)


def block_tool(i, name, data):
    return SimpleNamespace(type="tool_use", id=f"tu_{i}", name=name, input=data)


def response(content, stop):
    return SimpleNamespace(content=content, stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0))


class FakeClaude:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    async def create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)


@pytest.fixture
def fake(monkeypatch):
    from app import ai

    def install(script):
        f = FakeClaude(script)
        monkeypatch.setattr(ai, "client", lambda: f)
        monkeypatch.setattr(ai, "enabled", lambda: True)
        return f
    return install


async def setup(client):
    h = as_user(OWNER)
    b = (await client.post("/api/business", json={"name": "Торти", "kind": "fop", "fop_group": 3}, headers=h)).json()
    return b, h


async def ops_count():
    from app.database import SessionLocal
    from app.models import Operation
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(Operation))


async def test_free_text_makes_drafts_and_nothing_is_written_before_confirm(client, fake):
    b, h = await setup(client)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    f = fake([
        response([block_tool(1, "add_operation", {"kind": "income", "amount": 1350, "currency": None, "date": yesterday,
                                                   "category": "Продажи", "counterparty": None, "note": "3 торта"}),
                  block_tool(2, "add_operation", {"kind": "expense", "amount": 300, "currency": None, "date": yesterday,
                                                   "category": "Упаковка", "counterparty": None, "note": "упаковка"}),
                  block_tool(3, "add_debt", {"direction": "they_owe", "amount": 200, "counterparty": "Оля",
                                             "due_date": None, "note": None})], "tool_use"),
        response([block_text("Подготовил 3 записи, подтвердите.")], "end_turn"),
    ])
    r = await client.post("/api/ai/chat", json={"message": "вчера продала 3 торта по 450 и купила упаковку на 300, Оля должна 200"},
                          headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["drafts"]) == 3 and data["usage"]["used"] == 1
    assert await ops_count() == 0  # drafts only
    # The request follows the spec: strict tools, auto tool choice, cached system prompt, refusal fallback.
    call = f.calls[0]
    assert all(t["strict"] for t in call["tools"]) and call["tool_choice"] == {"type": "auto"}
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["fallbacks"] == "default" and call["model"] == "claude-opus-5-5"
    # all tool results go back in one user message
    results = [m for m in f.calls[1]["messages"] if m["role"] == "user"][-1]["content"]
    assert [x["type"] for x in results] == ["tool_result"] * 3 and not any(x["is_error"] for x in results)
    sales = data["drafts"][0]
    assert sales["category"] == "Продажи" and sales["occurred_at"] == yesterday
    for d in data["drafts"]:
        assert (await client.post(f"/api/ai/drafts/{d['id']}/confirm", headers=h)).json()["status"] == "done"
    assert await ops_count() == 2
    debts = (await client.get("/api/debts", headers=h)).json()
    assert float(debts["they_owe"]) == 200 and debts["items"][0]["counterparty"] == "Оля"
    # confirming twice is refused
    assert (await client.post(f"/api/ai/drafts/{sales['id']}/confirm", headers=h)).status_code == 409


async def test_refusal_and_quota(client, fake):
    b, h = await setup(client)
    fake([response([], "refusal")])
    data = (await client.post("/api/ai/chat", json={"message": "x"}, headers=h)).json()
    assert data["refused"] and data["drafts"] == []
    from app.database import SessionLocal
    from app.models import AiUsage, Business, utcnow
    async with SessionLocal() as s:
        row = await s.get(Business, b["id"])
        row.trial_until = utcnow() - timedelta(days=1)  # Free: 10 requests
        usage = await s.scalar(select(AiUsage))
        usage.requests = 10
        await s.commit()
    r = await client.post("/api/ai/chat", json={"message": "сколько я заработал?"}, headers=h)
    assert r.status_code == 402 and r.json()["detail"]["feature"] == "ai_requests"


async def test_read_tools_and_roles(client, fake):
    b, h = await setup(client)
    await client.post("/api/operations", json={"kind": "income", "amount": "5000"}, headers=h)
    today = date.today()
    f = fake([response([block_tool(1, "query_summary", {"date_from": today.replace(day=1).isoformat(),
                                                         "date_to": today.isoformat(), "group_by": "category"}),
                        block_tool(2, "get_tax_status", {})], "tool_use"),
              response([block_text("В этом месяце 5 000 ₴.")], "end_turn")])
    data = (await client.post("/api/ai/chat", json={"message": "сколько я заработал?"}, headers=h)).json()
    assert data["text"].startswith("В этом месяце")
    import json
    results = [m for m in f.calls[1]["messages"] if m["role"] == "user"][-1]["content"]
    summary = json.loads(results[0]["content"])
    assert summary["revenue"] == 5000 and summary["income_by_category"][0]["amount"] == 5000
    tax = json.loads(results[1]["content"])
    assert tax["group"] == 3 and tax["quarters"]

    # an accountant cannot get drafts that write
    from app.database import SessionLocal
    from app.models import Member
    async with SessionLocal() as s:
        s.add(Member(business_id=b["id"], telegram_id=6006, name="Бух", role="accountant"))
        await s.commit()
    f = fake([response([block_tool(1, "add_operation", {"kind": "expense", "amount": 10, "currency": None, "date": None,
                                                         "category": None, "counterparty": None, "note": None})], "tool_use"),
              response([block_text("Нет прав.")], "end_turn")])
    data = (await client.post("/api/ai/chat", json={"message": "запиши 10"}, headers=as_user(6006, b["id"]))).json()
    assert data["drafts"] == [] and [m for m in f.calls[1]["messages"] if m["role"] == "user"][-1]["content"][0]["is_error"] is True


def test_wants_ai_heuristic():
    from app.ai_bot import wants_ai
    assert wants_ai("сколько я заработал в октябре?")
    assert wants_ai("вчера продала 3 торта по 450 и купила упаковку на 300")
    assert not wants_ai("4500 продажа торт")
    assert not wants_ai("продал 3 торта по 450")
    assert not wants_ai("-1200 мука")


def test_token_encryption_roundtrip():
    from app import banks
    secret = "uXyZ-monobank-token-1234567890"
    enc = banks.encrypt(secret)
    assert secret not in enc and banks.decrypt(enc) == secret


async def test_mono_import_maps_and_deduplicates(client):
    from app import banks
    from app.database import SessionLocal
    from app.models import BankConnection, Business
    b, h = await setup(client)
    now = int(datetime.now(timezone.utc).timestamp())
    raw = [{"id": "A1", "time": now - 3600, "description": "Оплата від Іваненко", "amount": 150000, "currencyCode": 980},
           {"id": "A2", "time": now - 1800, "description": "Нова пошта доставка", "amount": -8550, "currencyCode": 980,
            "comment": "посилка"}]
    items = [banks.mono_to_operation(t) for t in raw]
    assert items[0]["kind"] == "income" and items[0]["amount"] == Decimal("1500")
    assert items[1]["kind"] == "expense" and items[1]["amount"] == Decimal("85.5")
    async with SessionLocal() as s:
        business = await s.get(Business, b["id"])
        conn = BankConnection(business_id=business.id, bank="mono", token_encrypted=banks.encrypt("t" * 30),
                              account_external_id="acc", account_id=None)
        s.add(conn)
        await s.flush()
        assert await banks.import_items(s, business, conn, items) == 2
        assert await banks.import_items(s, business, conn, items) == 0  # dedupe by bank_tx_id
        await s.commit()
    ops = (await client.get("/api/operations", headers=h)).json()["items"]
    assert {o["source"] for o in ops} == {"bank"}
    meta = (await client.get("/api/meta", headers=h)).json()
    delivery = next(c["id"] for c in meta["categories"] if c["key"] == "delivery")
    assert any(o["category_id"] == delivery for o in ops)
