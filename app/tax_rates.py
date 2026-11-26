"""Ukrainian FOP tax rates, limits and deadlines — one table per year.

Formulas in app/finance.py read everything from here; nothing is hard-coded there.
CHECK THESE VALUES BEFORE EVERY NEW YEAR against tax.gov.ua and the State Budget law:
the minimum wage (мінімальна заробітна плата) and the living wage (прожитковий мінімум)
on 1 January drive every number below.

The result is for reference only and does not replace an accountant.
"""
from __future__ import annotations

from decimal import Decimal as D

DISCLAIMER = {
    "ru": "Расчёт справочный и не заменяет бухгалтера. Ставки и лимиты проверяйте на сайте налоговой.",
    "uk": "Розрахунок довідковий і не замінює бухгалтера. Ставки й ліміти перевіряйте на сайті податкової.",
    "en": "For reference only, not a substitute for an accountant. Check rates and limits with the tax office.",
}

# year -> values. Amounts are UAH per month unless named otherwise.
TAX_RATES: dict[int, dict] = {
    2025: {
        "min_wage": D("8000.00"),
        "living_wage": D("3028.00"),
        "esv_rate": D("0.22"),
        "esv_month": D("1760.00"),            # 22% × min wage — the minimum ESV of a FOP for themselves
        "single_tax_month": {1: D("302.80"),  # group 1: up to 10% of the living wage
                             2: D("1600.00")},  # group 2: up to 20% of the min wage
        "group3_rate": {"no_vat": D("5"), "vat": D("3")},  # % of income
        "income_limit": {1: D("1336000"), 2: D("6672000"), 3: D("9336000")},  # per year (167/834/1167 min wages)
        "military_levy_month": D("800.00"),   # groups 1–2: 10% of the min wage per month
        "military_levy_group3_rate": D("1"),  # group 3: 1% of income
        "checked": "2025-01",
    },
    2026: {
        "min_wage": D("8647.00"),
        "living_wage": D("3328.00"),
        "esv_rate": D("0.22"),
        "esv_month": D("1902.34"),
        "single_tax_month": {1: D("332.80"), 2: D("1729.40")},
        "group3_rate": {"no_vat": D("5"), "vat": D("3")},
        "income_limit": {1: D("1444049"), 2: D("7211598"), 3: D("10091049")},
        "military_levy_month": D("864.70"),
        "military_levy_group3_rate": D("1"),
        "checked": "2026-01",
    },
}

DEADLINES = {
    # Group 3: the quarterly declaration is due 40 days after the quarter ends, the tax 10 days later.
    "group3_declaration_days": 40,
    "group3_payment_days": 50,
    # Groups 1–2 pay the single tax (and military levy) in advance, by this day of the current month.
    "group12_monthly_day": 20,
    # ESV for themselves: quarterly, by this day of the month after the quarter.
    "esv_quarter_day": 20,
}

# Thresholds (percent of the yearly income limit) that trigger a warning in the bot.
LIMIT_WARNINGS = (70, 90, 100)
# Days before a deadline when the bot reminds about taxes.
REMINDER_DAYS = (7, 1)


def rates_for(year: int) -> tuple[dict, bool]:
    """Rates of a year and whether they are exact (False = borrowed from the latest known year)."""
    if year in TAX_RATES:
        return TAX_RATES[year], True
    known = sorted(TAX_RATES)
    earlier = [y for y in known if y < year]
    return TAX_RATES[earlier[-1] if earlier else known[0]], False
