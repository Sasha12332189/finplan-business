from datetime import date
from decimal import Decimal as D

from app import finance, tax_rates
from app.finance import TaxProfile


def test_group3_quarter_five_percent_and_deadlines():
    t = finance.quarter_taxes(TaxProfile(fop_group=3, tax_rate=D("5")), 2026, 4, D("122400"))
    assert t["single_tax"] == D("6120.00")  # the spec's example: 6 120 ₴ for Q4
    assert t["military_levy"] == D("1224.00")  # 1% of income
    assert t["esv"] == D("5707.02")  # 3 × 1902.34
    assert t["due_date"] == date(2027, 2, 19)  # "до 19 февраля"
    assert t["declaration_date"] == date(2027, 2, 9)
    assert t["esv_due_date"] == date(2027, 1, 20)


def test_group3_vat_payer_rate_and_q1_deadline():
    assert finance.default_group3_rate(True, 2026) == D("3")
    assert finance.default_group3_rate(False, 2026) == D("5")
    t = finance.quarter_taxes(TaxProfile(fop_group=3, tax_rate=D("3"), is_vat_payer=True), 2026, 1, D("100000"))
    assert t["single_tax"] == D("3000.00")
    assert t["due_date"] == date(2026, 5, 20)
    assert t["esv_due_date"] == date(2026, 4, 20)


def test_groups_1_and_2_fixed_monthly_amounts():
    g1 = finance.quarter_taxes(TaxProfile(fop_group=1), 2026, 2, D("999999"))
    assert g1["single_tax"] == D("998.40")  # 3 × 332.80, independent of income
    g2 = finance.quarter_taxes(TaxProfile(fop_group=2), 2026, 2, D("0"))
    assert g2["single_tax"] == D("5188.20")  # 3 × 1729.40
    assert g2["military_levy"] == D("2594.10")  # 3 × 864.70
    pays = finance.monthly_payments(TaxProfile(fop_group=2), 2026, 3)
    assert pays[0] == {"what": "single_tax", "amount": D("1729.40"), "due_date": date(2026, 3, 20)}


def test_esv_can_be_off_and_non_fop_has_no_tax():
    t = finance.quarter_taxes(TaxProfile(fop_group=3, pays_esv=False), 2026, 1, D("1000"))
    assert t["esv"] == D("0")
    assert finance.quarter_taxes(TaxProfile(kind="company", fop_group=None), 2026, 1, D("1000"))["applicable"] is False


def test_rates_come_from_the_table():
    rates, exact = tax_rates.rates_for(2026)
    assert exact and rates["esv_month"] == (rates["min_wage"] * rates["esv_rate"]).quantize(D("0.01"))
    assert rates["income_limit"][3] == rates["min_wage"] * 1167
    assert rates["income_limit"][2] == rates["min_wage"] * 834
    assert rates["income_limit"][1] == rates["min_wage"] * 167
    future, exact = tax_rates.rates_for(2031)
    assert not exact and future is tax_rates.TAX_RATES[max(tax_rates.TAX_RATES)]


def test_income_limit_levels():
    profile = TaxProfile(fop_group=2)
    limit = tax_rates.TAX_RATES[2026]["income_limit"][2]
    assert finance.income_limit(profile, 2026, limit * D("0.5"))["level"] is None
    assert finance.income_limit(profile, 2026, limit * D("0.75"))["level"] == 70
    assert finance.income_limit(profile, 2026, limit * D("0.95"))["level"] == 90
    over = finance.income_limit(profile, 2026, limit + 1)
    assert over["level"] == 100 and over["left"] == 0
    assert finance.income_limit(TaxProfile(fop_group=None), 2026, D("1")) is None


def test_upcoming_payments_group3_in_february():
    profile = TaxProfile(fop_group=3, tax_rate=D("5"))
    incomes = {(2025, 4): D("100000"), (2026, 1): D("20000")}
    up = finance.upcoming_payments(profile, date(2026, 2, 1), incomes)
    first = up[0]
    assert first["what"] == "single_tax" and first["period"] == "2025-Q4"
    assert first["amount"] == D("6000.00")  # 5% + 1% military levy
    assert first["due_date"] == date(2026, 2, 19)
    assert any(p.get("accruing") and p["period"] == "2026-Q1" for p in up)
    # once marked paid the quarter disappears
    up = finance.upcoming_payments(profile, date(2026, 2, 1), incomes, {"2025-Q4"})
    assert all(p["period"] != "2025-Q4" for p in up)
