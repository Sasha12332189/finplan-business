import io
from datetime import date, timedelta

from conftest import as_user

OWNER = 3003


async def setup(client):
    h = as_user(OWNER)
    b = (await client.post("/api/business", json={"name": "Студія", "kind": "fop", "fop_group": 3}, headers=h)).json()
    meta = (await client.get("/api/meta", headers=h)).json()
    cats = {c["key"]: c["id"] for c in meta["categories"]}
    cp = (await client.post("/api/counterparties", json={"name": "Іваненко"}, headers=h)).json()
    for amount in ("1000", "2500"):
        await client.post("/api/operations", json={"kind": "income", "amount": amount, "category_id": cats["services"],
                                                   "counterparty_id": cp["id"]}, headers=h)
    await client.post("/api/operations", json={"kind": "expense", "amount": "400", "category_id": cats["materials"]}, headers=h)
    await client.post("/api/operations", json={"kind": "expense", "amount": "600", "category_id": cats["rent"]}, headers=h)
    return b, h, cp


async def test_report_data(client):
    b, h, cp = await setup(client)
    d = (await client.get("/api/reports?period=month", headers=h)).json()
    assert float(d["pnl"]["revenue"]) == 3500
    assert float(d["pnl"]["cogs"]) == 400
    assert float(d["pnl"]["gross_profit"]) == 3100
    assert float(d["pnl"]["operating"]) == 600
    assert float(d["pnl"]["profit"]) == 2500
    assert d["by_client"][0]["name"] == "Іваненко" and float(d["by_client"][0]["amount"]) == 3500
    assert {c["name"] for c in d["expense_by_category"]} >= {"Материалы", "Аренда"}  # the dev user speaks Russian


async def test_excel_has_all_sheets_and_live_formulas(client):
    from openpyxl import load_workbook

    from app import reports
    from app.database import SessionLocal
    from app.models import Business

    b, h, _ = await setup(client)
    async with SessionLocal() as s:
        business = await s.get(Business, b["id"])
        today = date.today()
        data = await reports.report_data(s, business, today.replace(day=1), today, with_operations=True)
        xlsx = reports.excel_bytes(business, data, "uk", insight="Витрати на матеріали зросли.")
        pdf = reports.pdf_bytes(business, data, "uk", insight="Витрати на матеріали зросли.")
        csv = reports.csv_bytes(data, "uk")
    wb = load_workbook(io.BytesIO(xlsx))
    assert wb.sheetnames == ["Зведення", "Операції", "За категоріями", "За місяцями", "Клієнти", "Податки",
                             "Книга обліку доходів"]
    summary = wb["Зведення"]
    assert summary["B5"].value.startswith("=SUMIF(")
    assert summary["B7"].value == "=B5-B6"
    ops = wb["Операції"]
    assert ops.auto_filter.ref and ops.freeze_panes == "A2"
    assert ops["A1"].fill.fgColor.rgb.endswith("3A5242")
    assert wb["За категоріями"]._charts and wb["За місяцями"]._charts
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000
    assert csv.decode("utf-8-sig").splitlines()[0].startswith("Дата;")


async def test_reports_send_requires_pro_and_bot(client):
    b, h, _ = await setup(client)
    # On trial (Pro) but no Telegram bot configured in tests -> 503, not a crash
    r = await client.post("/api/reports/send", json={"kind": "excel"}, headers=h)
    assert r.status_code == 503
    from app.database import SessionLocal
    from app.models import Business, utcnow
    async with SessionLocal() as s:
        row = await s.get(Business, b["id"])
        row.trial_until = utcnow() - timedelta(days=1)
        await s.commit()
    r = await client.post("/api/reports/send", json={"kind": "pdf"}, headers=h)
    assert r.status_code == 402
    # CSV stays free (fails only on the missing bot)
    assert (await client.post("/api/reports/send", json={"kind": "csv"}, headers=h)).status_code == 503


async def test_invoices_and_debts(client):
    b, h, cp = await setup(client)
    inv = (await client.post("/api/invoices", json={"counterparty_id": cp["id"], "items": [
        {"name": "Логотип", "qty": "3", "price": "2000"}]}, headers=h)).json()
    assert inv["number"] == 1 and float(inv["total"]) == 6000 and inv["status"] == "draft"
    r = await client.post(f"/api/invoices/{inv['id']}/paid", json={}, headers=h)
    assert r.json()["status"] == "paid" and r.json()["paid_operation_id"]
    d = (await client.get("/api/dashboard?period=month", headers=h)).json()
    assert float(d["summary"]["revenue"]) == 9500
    debt = (await client.post("/api/debts", json={"counterparty_id": cp["id"], "amount": "200", "note": "Оля"}, headers=h)).json()
    assert float((await client.get("/api/debts", headers=h)).json()["they_owe"]) == 200
    await client.post(f"/api/debts/{debt['id']}/close", json={"record_operation": True}, headers=h)
    assert float((await client.get("/api/debts", headers=h)).json()["they_owe"]) == 0


async def test_free_invoice_limit(client):
    b, h, cp = await setup(client)
    from app.database import SessionLocal
    from app.models import Business, utcnow
    async with SessionLocal() as s:
        row = await s.get(Business, b["id"])
        row.trial_until = utcnow() - timedelta(days=1)
        await s.commit()
    item = {"items": [{"name": "x", "qty": 1, "price": 1}]}
    for _ in range(5):
        assert (await client.post("/api/invoices", json=item, headers=h)).status_code == 200
    assert (await client.post("/api/invoices", json=item, headers=h)).status_code == 402


async def test_invoice_pdf_and_item_parser():
    from types import SimpleNamespace

    from app import documents
    from app.documents_bot import parse_item_lines
    items = parse_item_lines("Логотип 3 2000\nВізитки 1500")
    assert [(i["name"], int(i["qty"]), int(i["price"])) for i in items] == [("Логотип", 3, 2000), ("Візитки", 1, 1500)]
    inv = SimpleNamespace(number=7, items='[{"name": "Логотип", "qty": 3, "price": 2000, "sum": 6000}]', total=6000,
                          currency="UAH", created_at=date(2026, 11, 1), due_date=date(2026, 11, 8), note=None)
    business = SimpleNamespace(name="ФОП Тест", is_vat_payer=False)
    assert documents.invoice_pdf(business, inv, None, "uk").startswith(b"%PDF")
