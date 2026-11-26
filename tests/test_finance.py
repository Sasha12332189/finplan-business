from datetime import date
from decimal import Decimal as D

from app import finance
from app.finance import Op, parse_quick_entry, summarize


def test_profit_ignores_transfers_and_counts_cogs():
    ops = [
        Op("income", D("4500"), date(2026, 11, 2), counterparty_id=1),
        Op("income", D("1500"), date(2026, 11, 3), counterparty_id=2),
        Op("expense", D("1200"), date(2026, 11, 3), is_cogs=True),
        Op("expense", D("800"), date(2026, 11, 4)),
        Op("transfer", D("5000"), date(2026, 11, 4)),
    ]
    s = summarize(ops)
    assert s.revenue == D("6000")
    assert s.expenses == D("2000")
    assert s.profit == D("4000.00")
    assert s.gross_profit == D("4800.00")
    assert s.margin == D("66.7")
    assert s.sales_count == 2
    assert s.avg_check == D("3000.00")
    assert s.revenue_per_client == D("3000.00")


def test_product_cost_lowers_gross_profit_not_cash_profit():
    s = summarize([Op("income", D("1000"), date(2026, 1, 1), cogs_amount=D("400"))])
    assert s.profit == D("1000.00")
    assert s.gross_profit == D("600.00")


def test_margin_without_revenue_is_none():
    s = summarize([Op("expense", D("100"), date(2026, 1, 1))])
    assert s.margin is None and s.profit == D("-100.00") and s.avg_check is None


def test_pct_change():
    assert finance.pct_change(D("150"), D("100")) == D("50.0")
    assert finance.pct_change(D("50"), D("-100")) == D("150.0")
    assert finance.pct_change(D("10"), D("0")) is None


def test_period_ranges():
    today = date(2026, 11, 26)  # Thursday
    assert finance.period_range("today", today) == (today, today)
    assert finance.period_range("week", today) == (date(2026, 11, 23), date(2026, 11, 29))
    assert finance.period_range("month", today, -1) == (date(2026, 10, 1), date(2026, 10, 31))
    assert finance.period_range("quarter", today) == (date(2026, 10, 1), date(2026, 12, 31))
    assert finance.period_range("quarter", date(2026, 2, 1), -1) == (date(2025, 10, 1), date(2025, 12, 31))
    assert finance.period_range("year", today) == (date(2026, 1, 1), date(2026, 12, 31))
    # last month cut to the same day for a fair comparison
    assert finance.previous_comparable("month", today) == (date(2026, 10, 1), date(2026, 10, 26))
    assert finance.parse_period_key("2026-Q4") == (date(2026, 10, 1), date(2026, 12, 31))
    assert finance.parse_period_key("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))


def test_series():
    ops = [Op("income", D("10"), date(2026, 11, 1)), Op("expense", D("4"), date(2026, 11, 1)),
           Op("income", D("5"), date(2026, 12, 3))]
    days = finance.daily_series(ops, date(2026, 11, 1), date(2026, 11, 3))
    assert [d["income"] for d in days] == [D("10"), 0, 0]
    months = finance.monthly_series(ops, date(2026, 11, 1), date(2026, 12, 31))
    assert [m["net"] for m in months] == [D("6.00"), D("5.00")]


def test_quick_entry_examples_from_spec():
    e = parse_quick_entry("4500 продажа торт")
    assert (e.kind, e.amount, e.category_key) == ("income", D("4500.00"), "sales")
    e = parse_quick_entry("-1200 мука")
    assert (e.kind, e.amount, e.category_key) == ("expense", D("1200.00"), "materials")
    e = parse_quick_entry("1200 мука")
    assert e.kind == "expense" and e.category_key == "materials"
    e = parse_quick_entry("+15000 Иванов предоплата")
    assert (e.kind, e.amount, e.counterparty, e.category_key) == ("income", D("15000.00"), "Иванов", "prepayment")


def test_quick_entry_free_phrases():
    e = parse_quick_entry("продал 3 торта по 450")
    assert (e.kind, e.amount, e.quantity) == ("income", D("1350.00"), D("3"))
    e = parse_quick_entry("купил мешок муки за 900")
    assert (e.kind, e.amount, e.note) == ("expense", D("900.00"), "купил мешок муки")
    assert parse_quick_entry("12к реклама").amount == D("12000.00")
    assert parse_quick_entry("4500 кава").amount == D("4500.00")  # "к" of a word is not "thousand"
    assert parse_quick_entry("1 200 упаковка").amount == D("1200.00")
    assert parse_quick_entry("оренда 20000").note == "оренда"
    assert parse_quick_entry("привет") is None
    assert parse_quick_entry("/start") is None


def test_forecast_and_cash_gap():
    assert finance.forecast_month_end(D("10000"), date(2026, 11, 10)) == D("30000.00")
    rec = [{"kind": "expense", "amount": D("20000"), "day_of_month": 15, "note": "Аренда"},
           {"kind": "expense", "amount": D("500"), "day_of_month": 1, "note": "CRM"}]
    gap = finance.cash_gap(D("14300"), date(2026, 11, 10), rec)
    assert gap["date"] == date(2026, 11, 15) and gap["shortfall"] == D("5700.00")
    assert finance.cash_gap(D("50000"), date(2026, 11, 10), rec, horizon_days=20) is None
    # short month: day 31 lands on the 30th
    assert finance.next_occurrence(31, date(2026, 11, 2)) == date(2026, 11, 30)


def test_money_format():
    assert finance.money(D("1234.5"), "UAH").replace(" ", " ") == "1 234.50 ₴"
    assert finance.money(D("-20"), "USD", sign=True) == "−20 $"
