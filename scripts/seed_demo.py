"""Fill a local database with a demo business (for screenshots and trying the Mini App).

    DEBUG=true python -m scripts.seed_demo 1001
    DEBUG=true uvicorn app.main:app   →  http://localhost:8000/?dev=1001
"""
from __future__ import annotations

import asyncio
import random
import sys
from datetime import timedelta
from decimal import Decimal

from app import finance, services
from app.database import SessionLocal, init_database
from app.models import Counterparty, Debt, Invoice, Product, RecurringOperation


async def main(telegram_id: int) -> None:
    await init_database()
    random.seed(7)
    async with SessionLocal() as s:
        user = await services.ensure_user(s, telegram_id, "Оля", None, "ru")
        user.language = "ru"
        business, member = await services.create_business(s, user, "Торты Оли", "fop", 3, False, language="ru")
        cats = {c.key: c for c in await services.categories(s, business.id)}
        accounts, _ = await services.account_balances(s, business)
        card = accounts[1]["id"]
        clients = []
        for name in ("Кофейня «Зерно»", "Иванов", "Марина Ковальчук", "Студия Bloom"):
            c = Counterparty(business_id=business.id, name=name, kind="client")
            s.add(c)
            clients.append(c)
        supplier = Counterparty(business_id=business.id, name="Метро", kind="supplier")
        s.add(supplier)
        await s.flush()
        today = finance.local_today(business.timezone)
        for back in range(0, 75):
            day = today - timedelta(days=back)
            for _ in range(random.randint(0, 3)):
                cp = random.choice(clients + [None, None])
                await services.record_operation(
                    s, business, member, kind="income", amount=Decimal(random.choice([450, 900, 1350, 1800, 2400, 3200])),
                    category_id=cats["sales"].id, counterparty_id=cp.id if cp else None, account_id=card,
                    note=random.choice(["торт", "капкейки", "чизкейк", "торт на заказ"]), occurred_at=day, source="bot")
            if back % 3 == 0:
                await services.record_operation(
                    s, business, member, kind="expense", amount=Decimal(random.choice([300, 650, 900, 1200])),
                    category_id=random.choice([cats["materials"], cats["packaging"]]).id, counterparty_id=supplier.id,
                    account_id=card, note=random.choice(["мука", "сливки", "коробки", "ягоды"]), occurred_at=day, source="bot")
            if back % 14 == 2:
                await services.record_operation(s, business, member, kind="expense", amount=Decimal("1500"),
                                                category_id=cats["ads"].id, note="таргет Instagram", occurred_at=day)
        for back in (5, 35, 65):
            await services.record_operation(s, business, member, kind="expense", amount=Decimal("8000"),
                                            category_id=cats["rent"].id, note="аренда цеха",
                                            occurred_at=today - timedelta(days=back))
        s.add(RecurringOperation(business_id=business.id, kind="expense", amount=Decimal("8000"), note="Аренда цеха",
                                 category_id=cats["rent"].id, day_of_month=15,
                                 next_date=finance.next_occurrence(15, today + timedelta(days=1))))
        business.invoice_counter = 14
        s.add(Invoice(business_id=business.id, number=14, counterparty_id=clients[1].id, total=Decimal("6000"),
                      items='[{"name": "Торт на юбилей", "qty": 2, "price": 3000}]', status="sent",
                      due_date=today - timedelta(days=3)))
        s.add(Debt(business_id=business.id, counterparty_id=clients[2].id, direction="they_owe", amount=Decimal("200"),
                   due_date=today + timedelta(days=4)))
        s.add(Product(business_id=business.id, name="Торт «Наполеон»", unit="шт", cost_price=Decimal("380"),
                      sale_price=Decimal("900"), stock_qty=Decimal("6")))
        await s.commit()
        print("Demo business", business.id, "for Telegram id", telegram_id)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 1001))
