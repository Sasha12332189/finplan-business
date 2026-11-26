"""Report data (the Reports screen), Excel (openpyxl) and PDF (reportlab) files, CSV export.

Files are built on the server and sent to the bot chat (send_document): that works inside
Telegram on iPhone, where downloads from the Mini App WebView do not.
"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from . import finance, services
from .finance import ZERO, q2
from .models import Account, Business, Category, Counterparty, Debt, Invoice, Member, Operation, Project
from .tax_rates import DISCLAIMER

LABELS = {
    "ru": {"summary": "Сводка", "operations": "Операции", "by_category": "По категориям", "by_month": "По месяцам",
           "clients": "Клиенты", "taxes": "Налоги", "book": "Книга учёта доходов", "period": "Период",
           "revenue": "Выручка", "expenses": "Расходы", "profit": "Прибыль", "margin": "Маржа", "cogs": "Себестоимость",
           "gross": "Валовая прибыль", "tax": "Налог (ЕН + ВС)", "previous": "Прошлый период", "change": "Изменение",
           "date": "Дата", "type": "Тип", "amount": "Сумма", "currency": "Валюта", "amount_base": "Сумма в валюте бизнеса",
           "category": "Категория", "client": "Контрагент", "project": "Проект", "member": "Сотрудник", "note": "Комментарий",
           "income": "Доход", "expense": "Расход", "transfer": "Перевод", "total": "Итого", "share": "Доля",
           "month": "Месяц", "net": "Чистый поток", "debt": "Долг клиента", "count": "Операций", "quarter": "Квартал",
           "income_total": "Доход", "single_tax": "Единый налог", "military_levy": "Военный сбор", "esv": "ЕСВ",
           "due": "Срок уплаты", "status": "Статус", "paid": "Оплачено", "to_pay": "К оплате", "no": "№",
           "book_note": "Сумма дохода, грн", "title": "Отчёт", "top_categories": "Топ расходов", "ai": "Вывод",
           "generated": "Сформировано finplan Business", "sales": "Продаж", "avg": "Средний чек"},
    "uk": {"summary": "Зведення", "operations": "Операції", "by_category": "За категоріями", "by_month": "За місяцями",
           "clients": "Клієнти", "taxes": "Податки", "book": "Книга обліку доходів", "period": "Період",
           "revenue": "Виручка", "expenses": "Витрати", "profit": "Прибуток", "margin": "Маржа", "cogs": "Собівартість",
           "gross": "Валовий прибуток", "tax": "Податок (ЄП + ВЗ)", "previous": "Минулий період", "change": "Зміна",
           "date": "Дата", "type": "Тип", "amount": "Сума", "currency": "Валюта", "amount_base": "Сума у валюті бізнесу",
           "category": "Категорія", "client": "Контрагент", "project": "Проєкт", "member": "Працівник", "note": "Коментар",
           "income": "Дохід", "expense": "Витрата", "transfer": "Переказ", "total": "Разом", "share": "Частка",
           "month": "Місяць", "net": "Чистий потік", "debt": "Борг клієнта", "count": "Операцій", "quarter": "Квартал",
           "income_total": "Дохід", "single_tax": "Єдиний податок", "military_levy": "Військовий збір", "esv": "ЄСВ",
           "due": "Строк сплати", "status": "Статус", "paid": "Сплачено", "to_pay": "До сплати", "no": "№",
           "book_note": "Сума доходу, грн", "title": "Звіт", "top_categories": "Топ витрат", "ai": "Висновок",
           "generated": "Сформовано finplan Business", "sales": "Продажів", "avg": "Середній чек"},
}


def L(lang: str) -> dict:
    return LABELS["ru" if lang == "ru" else "uk"]


# ---------------------------------------------------------------- data

async def names(session, model, business_id: int) -> dict[int, str]:
    rows = await session.execute(select(model.id, model.name).where(model.business_id == business_id))
    return dict(rows.all())


def previous_range(start: date, end: date) -> tuple[date, date]:
    length = (end - start).days + 1
    # Whole months compare with the previous whole months.
    if start.day == 1 and (end + timedelta(days=1)).day == 1:
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        y, m = finance.shift_month(start.year, start.month, -months)
        py, pm = finance.shift_month(start.year, start.month, -1)
        return date(y, m, 1), finance.month_range(py, pm)[1]
    return start - timedelta(days=length), start - timedelta(days=1)


def grouped(rows: dict, labels: dict, kind: str, total: Decimal) -> list[dict]:
    out = []
    for key, v in rows.items():
        if v[kind] <= 0:
            continue
        out.append({"id": key, "name": labels.get(key) or ("—" if key is None else "?"), "amount": q2(v[kind]), "count": v["count"],
                    "share": float(v[kind] / total * 100) if total else 0.0})
    return sorted(out, key=lambda r: r["amount"], reverse=True)


async def report_data(session, business: Business, start: date, end: date, *, with_operations: bool = False) -> dict:
    ops = await services.load_ops(session, business.id, start, end)
    s = finance.summarize(ops)
    ps, pe = previous_range(start, end)
    prev = finance.summarize(await services.load_ops(session, business.id, ps, pe))
    cats = await names(session, Category, business.id)
    cps = await names(session, Counterparty, business.id)
    projects = await names(session, Project, business.id)
    members = await names(session, Member, business.id)
    by_cat = finance.group_totals(ops, "category_id")
    by_client = finance.group_totals(ops, "counterparty_id")
    # The cash flow shows at least the last 6 months, so a single month still has context.
    sy, sm = finance.shift_month(end.year, end.month, -5)
    month_start = min(date(start.year, start.month, 1), date(sy, sm, 1))
    cash = finance.monthly_series(await services.load_ops(session, business.id, month_start, end), month_start, end)
    data = {
        "start": start, "end": end, "previous_start": ps, "previous_end": pe, "currency": business.currency,
        "summary": s.as_dict(), "previous": prev.as_dict(),
        "change": {k: finance.pct_change(getattr(s, k), getattr(prev, k)) for k in ("revenue", "expenses", "profit")},
        "pnl": {"revenue": q2(s.revenue), "cogs": q2(s.cogs), "gross_profit": s.gross_profit,
                "operating": q2(s.expenses - (s.cogs - sum((o.cogs_amount or ZERO) for o in ops))),
                "profit": q2(s.gross_profit - (s.expenses - (s.cogs - sum((o.cogs_amount or ZERO) for o in ops))))},
        "income_by_category": grouped(by_cat, cats, "income", s.revenue),
        "expense_by_category": grouped(by_cat, cats, "expense", s.expenses),
        "by_client": grouped(by_client, cps, "income", s.revenue),
        "by_project": grouped(finance.group_totals(ops, "project_id"), projects, "income", s.revenue),
        "by_project_expense": grouped(finance.group_totals(ops, "project_id"), projects, "expense", s.expenses),
        "by_member": grouped(finance.group_totals(ops, "member_id"), members, "income", s.revenue),
        "cashflow": cash,
    }
    if with_operations:
        accounts = await names(session, Account, business.id)
        rows = (await session.scalars(select(Operation).where(
            Operation.business_id == business.id, Operation.occurred_at >= start, Operation.occurred_at <= end)
            .order_by(Operation.occurred_at, Operation.id))).all()
        data["operations"] = [{
            "date": o.occurred_at, "kind": o.kind, "amount": q2(o.amount), "currency": o.currency,
            "amount_base": q2(o.amount_base), "category": cats.get(o.category_id, ""), "client": cps.get(o.counterparty_id, ""),
            "project": projects.get(o.project_id, ""), "member": members.get(o.member_id, ""), "note": o.note or "",
            "account": accounts.get(o.account_id, "")} for o in rows]
        debts = (await session.scalars(select(Debt).where(Debt.business_id == business.id, Debt.status == "open",
                                                          Debt.direction == "they_owe"))).all()
        owed: dict[int | None, Decimal] = {}
        for d in debts:
            owed[d.counterparty_id] = owed.get(d.counterparty_id, ZERO) + Decimal(d.amount)
        invoices = (await session.scalars(select(Invoice).where(Invoice.business_id == business.id,
                                                                Invoice.status.in_(("sent", "overdue"))))).all()
        for inv in invoices:
            owed[inv.counterparty_id] = owed.get(inv.counterparty_id, ZERO) + Decimal(inv.total)
        data["client_debts"] = {cps.get(k, "—"): q2(v) for k, v in owed.items()}
        data["taxes"] = await services.tax_overview(session, business, year=end.year)
    return data


# ---------------------------------------------------------------- CSV (free for everyone)

def csv_bytes(data: dict, lang: str) -> bytes:
    lb = L(lang)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([lb["date"], lb["type"], lb["amount"], lb["currency"], lb["amount_base"], lb["category"], lb["client"],
                lb["project"], lb["member"], lb["note"]])
    for o in data["operations"]:
        w.writerow([o["date"].isoformat(), lb[o["kind"]], str(o["amount"]).replace(".", ","), o["currency"],
                    str(o["amount_base"]).replace(".", ","), o["category"], o["client"], o["project"], o["member"], o["note"]])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")  # BOM: Excel opens Cyrillic correctly


# ---------------------------------------------------------------- Excel

GREEN, STRIPE, INCOME, EXPENSE = "3A5242", "F4F5F1", "2E8A5E", "C0654C"


def excel_bytes(business: Business, data: dict, lang: str, insight: str | None = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    lb = L(lang)
    cur = business.currency
    money_fmt = f'#,##0.00 "{finance.CURRENCY_SIGNS.get(cur, cur)}";[Red]-#,##0.00 "{finance.CURRENCY_SIGNS.get(cur, cur)}"'
    head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor=GREEN)
    stripe = PatternFill("solid", fgColor=STRIPE)
    thin = Border(bottom=Side(style="thin", color="DCE2DC"))
    wb = Workbook()

    def header(ws, row: int, values: list[str]):
        for i, v in enumerate(values, 1):
            c = ws.cell(row=row, column=i, value=v)
            c.font, c.fill = head_font, head_fill
            c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = 30

    def widths(ws, values: list[int]):
        for i, w in enumerate(values, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

    def stripes(ws, first: int, last: int, cols: int):
        for r in range(first, last + 1):
            for c in range(1, cols + 1):
                cell = ws.cell(row=r, column=c)
                cell.border = thin
                if (r - first) % 2 == 1:
                    cell.fill = stripe

    period = f"{data['start']:%d.%m.%Y} – {data['end']:%d.%m.%Y}"

    # 2. Operations (built first: the summary formulas point at it)
    ops_ws = wb.active
    ops_ws.title = lb["operations"]
    header(ops_ws, 1, [lb["date"], lb["type"], lb["amount_base"], lb["amount"], lb["currency"], lb["category"],
                       lb["client"], lb["project"], lb["member"], lb["note"]])
    ops = data.get("operations", [])
    for i, o in enumerate(ops, 2):
        ops_ws.cell(row=i, column=1, value=o["date"]).number_format = "DD.MM.YYYY"
        ops_ws.cell(row=i, column=2, value=lb[o["kind"]])
        c = ops_ws.cell(row=i, column=3, value=float(o["amount_base"]))
        c.number_format = money_fmt
        c.font = Font(color=INCOME if o["kind"] == "income" else EXPENSE if o["kind"] == "expense" else "6A766E")
        ops_ws.cell(row=i, column=4, value=float(o["amount"])).number_format = "#,##0.00"
        for col, key in enumerate(("currency", "category", "client", "project", "member", "note"), 5):
            ops_ws.cell(row=i, column=col, value=o[key])
    last = max(len(ops) + 1, 2)
    stripes(ops_ws, 2, last, 10)
    ops_ws.auto_filter.ref = f"A1:J{last}"
    ops_ws.freeze_panes = "A2"
    widths(ops_ws, [12, 10, 16, 12, 8, 20, 22, 16, 16, 36])
    ops_range = f"'{lb['operations']}'!$B$2:$B${last}"
    sum_range = f"'{lb['operations']}'!$C$2:$C${last}"
    cat_range = f"'{lb['operations']}'!$F$2:$F${last}"
    client_range = f"'{lb['operations']}'!$G$2:$G${last}"
    date_range = f"'{lb['operations']}'!$A$2:$A${last}"

    # 1. Summary
    ws = wb.create_sheet(lb["summary"], 0)
    ws["A1"] = f"{business.name} · {lb['title']}"
    ws["A1"].font = Font(bold=True, size=16, color=GREEN)
    ws["A2"] = f"{lb['period']}: {period}"
    ws["A2"].font = Font(color="6A766E")
    header(ws, 4, ["", lb["period"], lb["previous"], lb["change"]])
    prev = data["previous"]
    rows = [
        (lb["revenue"], f'=SUMIF({ops_range},"{lb["income"]}",{sum_range})', prev["revenue"]),
        (lb["expenses"], f'=SUMIF({ops_range},"{lb["expense"]}",{sum_range})', prev["expenses"]),
        (lb["profit"], "=B5-B6", prev["profit"]),
        (lb["margin"], '=IF(B5=0,"",B7/B5)', (prev["profit"] / prev["revenue"]) if prev["revenue"] else None),
        (lb["cogs"], float(data["summary"]["cogs"]), prev["cogs"]),
        (lb["gross"], "=B5-B9", prev["gross_profit"]),
    ]
    for i, (name, value, previous) in enumerate(rows, 5):
        ws.cell(row=i, column=1, value=name).font = Font(bold=True)
        ws.cell(row=i, column=2, value=value)
        ws.cell(row=i, column=3, value=float(previous) if previous is not None else None)
        ws.cell(row=i, column=4, value=f'=IF(OR(C{i}="",C{i}=0),"",(B{i}-C{i})/ABS(C{i}))')
        fmt = "0.0%" if name == lb["margin"] else money_fmt
        ws.cell(row=i, column=2).number_format = ws.cell(row=i, column=3).number_format = fmt
        ws.cell(row=i, column=4).number_format = "+0.0%;-0.0%"
    taxes = data.get("taxes") or {}
    tax_total = sum((q["single_tax"] + q["military_levy"]) for q in taxes.get("quarters", [])
                    if not q.get("future") and finance.quarter_range(q["year"], q["quarter"])[1] >= data["start"]
                    and finance.quarter_range(q["year"], q["quarter"])[0] <= data["end"]) if taxes.get("applicable") else None
    ws.cell(row=11, column=1, value=lb["tax"]).font = Font(bold=True)
    if tax_total is not None:
        ws.cell(row=11, column=2, value=float(tax_total)).number_format = money_fmt
    ws.cell(row=12, column=1, value=lb["sales"]).font = Font(bold=True)
    ws.cell(row=12, column=2, value=f'=COUNTIF({ops_range},"{lb["income"]}")')
    ws.cell(row=13, column=1, value=lb["avg"]).font = Font(bold=True)
    ws.cell(row=13, column=2, value='=IF(B12=0,"",B5/B12)').number_format = money_fmt
    stripes(ws, 5, 13, 4)
    if insight:
        ws.cell(row=15, column=1, value=lb["ai"]).font = Font(bold=True, color=GREEN)
        ws.cell(row=16, column=1, value=insight).alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells("A16:D20")
    ws.cell(row=22, column=1, value=DISCLAIMER["ru" if lang == "ru" else "uk"]).font = Font(italic=True, size=9, color="6A766E")
    widths(ws, [26, 18, 18, 12])

    # 3. By category (live SUMIF from the operations sheet) + pie chart
    ws = wb.create_sheet(lb["by_category"])
    header(ws, 1, [lb["category"], lb["type"], lb["amount"], lb["share"]])
    r = 2
    groups = [(lb["income"], data["income_by_category"]), (lb["expense"], data["expense_by_category"])]
    first_expense = None
    for kind_label, items in groups:
        if kind_label == lb["expense"]:
            first_expense = r
        for item in items:
            ws.cell(row=r, column=1, value=item["name"])
            ws.cell(row=r, column=2, value=kind_label)
            ws.cell(row=r, column=3, value=f'=SUMIFS({sum_range},{cat_range},A{r},{ops_range},B{r})').number_format = money_fmt
            ws.cell(row=r, column=4, value=f'=C{r}/SUMIF($B$2:$B${max(r, 2)}0,B{r},$C$2:$C${max(r, 2)}0)')
            r += 1
    for row in range(2, r):  # fix the share denominators now that the table size is known
        ws.cell(row=row, column=4, value=f'=IFERROR(C{row}/SUMIF($B$2:$B${r - 1},B{row},$C$2:$C${r - 1}),"")').number_format = "0.0%"
    ws.cell(row=r, column=1, value=lb["total"]).font = Font(bold=True)
    ws.cell(row=r, column=3, value=f"=SUM(C2:C{r - 1})" if r > 2 else 0).number_format = money_fmt
    stripes(ws, 2, max(r - 1, 2), 4)
    widths(ws, [26, 12, 18, 10])
    exp_items = data["expense_by_category"]
    if exp_items and first_expense:
        pie = PieChart()
        pie.title = lb["expenses"]
        pie.add_data(Reference(ws, min_col=3, min_row=first_expense, max_row=first_expense + len(exp_items) - 1))
        pie.set_categories(Reference(ws, min_col=1, min_row=first_expense, max_row=first_expense + len(exp_items) - 1))
        pie.height, pie.width = 8, 12
        ws.add_chart(pie, "F2")

    # 4. By month + line chart
    ws = wb.create_sheet(lb["by_month"])
    header(ws, 1, [lb["month"], lb["revenue"], lb["expenses"], lb["net"]])
    cash = data["cashflow"]
    for i, m in enumerate(cash, 2):
        y, mo = map(int, m["month"].split("-"))
        first_day, last_day = finance.month_range(y, mo)
        ws.cell(row=i, column=1, value=m["month"])
        ws.cell(row=i, column=2, value=f'=SUMIFS({sum_range},{ops_range},"{lb["income"]}",{date_range},">="&DATE({y},{mo},1),{date_range},"<="&DATE({y},{mo},{last_day.day}))')
        ws.cell(row=i, column=3, value=f'=SUMIFS({sum_range},{ops_range},"{lb["expense"]}",{date_range},">="&DATE({y},{mo},1),{date_range},"<="&DATE({y},{mo},{last_day.day}))')
        ws.cell(row=i, column=4, value=f"=B{i}-C{i}")
        for c in (2, 3, 4):
            ws.cell(row=i, column=c).number_format = money_fmt
    end_row = len(cash) + 1
    ws.cell(row=end_row + 1, column=1, value=lb["total"]).font = Font(bold=True)
    for c, col in ((2, "B"), (3, "C"), (4, "D")):
        ws.cell(row=end_row + 1, column=c, value=f"=SUM({col}2:{col}{end_row})").number_format = money_fmt
    stripes(ws, 2, end_row, 4)
    widths(ws, [12, 18, 18, 18])
    if cash:
        line = LineChart()
        line.title = f"{lb['revenue']} / {lb['expenses']}"
        line.add_data(Reference(ws, min_col=2, min_row=1, max_col=3, max_row=end_row), titles_from_data=True)
        line.set_categories(Reference(ws, min_col=1, min_row=2, max_row=end_row))
        line.height, line.width = 8, 16
        try:
            line.series[0].graphicalProperties.line.solidFill = INCOME
            line.series[1].graphicalProperties.line.solidFill = EXPENSE
        except Exception:
            pass
        ws.add_chart(line, "F2")

    # 5. Clients
    ws = wb.create_sheet(lb["clients"])
    header(ws, 1, [lb["client"], lb["revenue"], lb["count"], lb["debt"]])
    debts = data.get("client_debts", {})
    clients = data["by_client"]
    names_seen = set()
    for i, c in enumerate(clients, 2):
        ws.cell(row=i, column=1, value=c["name"])
        ws.cell(row=i, column=2, value=f'=SUMIFS({sum_range},{client_range},A{i},{ops_range},"{lb["income"]}")').number_format = money_fmt
        ws.cell(row=i, column=3, value=c["count"])
        ws.cell(row=i, column=4, value=float(debts.get(c["name"], 0)) or None).number_format = money_fmt
        names_seen.add(c["name"])
    r = len(clients) + 2
    for name, amount in debts.items():
        if name not in names_seen:
            ws.cell(row=r, column=1, value=name)
            ws.cell(row=r, column=4, value=float(amount)).number_format = money_fmt
            r += 1
    ws.cell(row=r, column=1, value=lb["total"]).font = Font(bold=True)
    ws.cell(row=r, column=2, value=f"=SUM(B2:B{r - 1})" if r > 2 else 0).number_format = money_fmt
    ws.cell(row=r, column=4, value=f"=SUM(D2:D{r - 1})" if r > 2 else 0).number_format = money_fmt
    stripes(ws, 2, max(r - 1, 2), 4)
    widths(ws, [28, 18, 10, 16])
    if clients:
        bar = BarChart()
        bar.type, bar.title = "bar", lb["revenue"]
        top = min(len(clients), 10)
        bar.add_data(Reference(ws, min_col=2, min_row=1, max_row=top + 1), titles_from_data=True)
        bar.set_categories(Reference(ws, min_col=1, min_row=2, max_row=top + 1))
        bar.height, bar.width, bar.legend = 8, 14, None
        ws.add_chart(bar, "F2")

    # 6. Taxes
    ws = wb.create_sheet(lb["taxes"])
    if taxes.get("applicable"):
        header(ws, 1, [lb["quarter"], lb["income_total"], lb["single_tax"], lb["military_levy"], lb["esv"], lb["total"],
                       lb["due"], lb["status"]])
        r = 2
        for q in taxes["quarters"]:
            if q.get("future"):
                continue
            ws.cell(row=r, column=1, value=q["period"])
            for c, key in ((2, "income_total"), (3, "single_tax"), (4, "military_levy"), (5, "esv")):
                ws.cell(row=r, column=c, value=float(q[key])).number_format = money_fmt
            ws.cell(row=r, column=6, value=f"=C{r}+D{r}+E{r}").number_format = money_fmt
            ws.cell(row=r, column=7, value=q["due_date"]).number_format = "DD.MM.YYYY"
            ws.cell(row=r, column=8, value=lb["paid"] if q["status"] == "paid" else lb["to_pay"])
            r += 1
        ws.cell(row=r, column=1, value=lb["total"]).font = Font(bold=True)
        for c in range(2, 7):
            col = get_column_letter(c)
            ws.cell(row=r, column=c, value=f"=SUM({col}2:{col}{r - 1})" if r > 2 else 0).number_format = money_fmt
        stripes(ws, 2, max(r - 1, 2), 8)
        ws.cell(row=r + 2, column=1, value=DISCLAIMER["ru" if lang == "ru" else "uk"]).font = Font(italic=True, size=9, color="6A766E")
    else:
        ws["A1"] = "—"
    widths(ws, [12, 16, 16, 16, 16, 16, 14, 12])

    # 7. Income book (книга обліку доходів for FOP groups 1–3: date and income amount per day)
    ws = wb.create_sheet(lb["book"][:31])
    ws["A1"] = f"{lb['book']} · {business.name} · {period}"
    ws["A1"].font = Font(bold=True, color=GREEN)
    header(ws, 3, [lb["no"], lb["date"], lb["book_note"], lb["note"]])
    by_day: dict[date, Decimal] = {}
    for o in ops:
        if o["kind"] == "income":
            by_day[o["date"]] = by_day.get(o["date"], ZERO) + Decimal(o["amount_base"])
    r = 4
    for n, (day, amount) in enumerate(sorted(by_day.items()), 1):
        ws.cell(row=r, column=1, value=n)
        ws.cell(row=r, column=2, value=day).number_format = "DD.MM.YYYY"
        ws.cell(row=r, column=3, value=float(amount)).number_format = "#,##0.00"
        r += 1
    ws.cell(row=r, column=2, value=lb["total"]).font = Font(bold=True)
    ws.cell(row=r, column=3, value=f"=SUM(C4:C{r - 1})" if r > 4 else 0).number_format = "#,##0.00"
    stripes(ws, 4, max(r - 1, 4), 4)
    widths(ws, [6, 14, 20, 30])

    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines = False
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- PDF

FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    (os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf"), os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans-Bold.ttf")),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
]
_fonts: tuple[str, str] | None = None


def pdf_fonts() -> tuple[str, str]:
    """Register a TTF font with Cyrillic letters (DejaVu on Railway via the Dockerfile)."""
    global _fonts
    if _fonts:
        return _fonts
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for regular, bold in FONT_CANDIDATES:
        if os.path.exists(regular):
            pdfmetrics.registerFont(TTFont("FB", regular))
            pdfmetrics.registerFont(TTFont("FB-Bold", bold if os.path.exists(bold) else regular))
            _fonts = ("FB", "FB-Bold")
            return _fonts
    _fonts = ("Helvetica", "Helvetica-Bold")  # no Cyrillic: install fonts-dejavu-core
    return _fonts


def _wrap(c, text: str, font: str, size: float, width: float) -> list[str]:
    words, lines, line = (text or "").split(), [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if c.stringWidth(trial, font, size) <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def pdf_bytes(business: Business, data: dict, lang: str, insight: str | None = None) -> bytes:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    lb = L(lang)
    font, bold = pdf_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    M = 40
    ink, muted, line_c = HexColor("#1C2620"), HexColor("#6A766E"), HexColor("#DCE2DC")
    primary, primary2, inc, exp = HexColor("#3A5242"), HexColor("#546E5C"), HexColor("#2E8A5E"), HexColor("#C0654C")
    cur = business.currency
    c.setTitle(f"{business.name} — {lb['title']}")

    def money(v):
        return finance.money(v, cur).replace("\u202f", " ")

    # header: the logo's two circles
    c.setFillColor(HexColor("#F4F5F1"))
    c.rect(0, H - 110, W, 110, stroke=0, fill=1)
    c.setFillColor(primary)
    c.circle(M + 12, H - 52, 12, stroke=0, fill=1)
    c.setFillColor(primary2)
    c.circle(M + 26, H - 52, 12, stroke=0, fill=1)
    c.setFillColor(ink)
    c.setFont(bold, 18)
    c.drawString(M + 50, H - 50, business.name[:48])
    c.setFont(font, 10)
    c.setFillColor(muted)
    c.drawString(M + 50, H - 66, f"{lb['title']} · {data['start']:%d.%m.%Y} – {data['end']:%d.%m.%Y}")

    # KPI cards
    s, ch = data["summary"], data["change"]
    kpis = [(lb["revenue"], s["revenue"], ch.get("revenue"), True), (lb["expenses"], s["expenses"], ch.get("expenses"), False),
            (lb["profit"], s["profit"], ch.get("profit"), True),
            (lb["margin"], f"{s['margin']}%" if s["margin"] is not None else "—", None, True)]
    cw, chh, y = (W - 2 * M - 30) / 4, 64, H - 190
    for i, (name, value, pct, good_up) in enumerate(kpis):
        x = M + i * (cw + 10)
        c.setFillColor(HexColor("#FFFFFF"))
        c.setStrokeColor(line_c)
        c.roundRect(x, y, cw, chh, 10, stroke=1, fill=1)
        c.setFillColor(muted)
        c.setFont(font, 8.5)
        c.drawString(x + 10, y + chh - 16, name)
        c.setFillColor(ink)
        c.setFont(bold, 13)
        c.drawString(x + 10, y + chh - 36, value if isinstance(value, str) else money(value))
        if pct is not None:
            good = (pct >= 0) == good_up
            c.setFillColor(inc if good else exp)
            c.setFont(bold, 8.5)
            c.drawString(x + 10, y + 10, f"{'+' if pct > 0 else ''}{pct}%")

    # bar chart by month (or by day for a single month)
    cash = data["cashflow"]
    top = y - 30
    c.setFillColor(ink)
    c.setFont(bold, 11)
    c.drawString(M, top, f"{lb['revenue']} / {lb['expenses']}")
    ch_top, ch_bottom = top - 14, top - 170
    c.setStrokeColor(line_c)
    c.line(M, ch_bottom, W - M, ch_bottom)
    if cash:
        mx = max([float(m["income"]) for m in cash] + [float(m["expense"]) for m in cash] + [1])
        slot = (W - 2 * M) / len(cash)
        bw = min(26, slot * 0.32)
        for i, m in enumerate(cash):
            cx = M + i * slot + slot / 2
            for j, (val, col) in enumerate(((float(m["income"]), primary), (float(m["expense"]), exp))):
                h = (val / mx) * (ch_top - ch_bottom - 14)
                c.setFillColor(col)
                c.rect(cx - bw - 1 + j * (bw + 2), ch_bottom, bw, max(h, 0.5), stroke=0, fill=1)
            c.setFillColor(muted)
            c.setFont(font, 8)
            c.drawCentredString(cx, ch_bottom - 12, m["month"][5:] + "." + m["month"][2:4])

    # P&L and top expense categories
    y2 = ch_bottom - 44
    c.setFillColor(ink)
    c.setFont(bold, 11)
    c.drawString(M, y2, "P&L")
    pnl = data["pnl"]
    rows = [(lb["revenue"], pnl["revenue"]), (lb["cogs"], -pnl["cogs"]), (lb["gross"], pnl["gross_profit"]),
            (lb["expenses"], -pnl["operating"]), (lb["profit"], pnl["profit"])]
    yy = y2 - 18
    for name, v in rows:
        c.setFont(bold if name in (lb["gross"], lb["profit"]) else font, 9.5)
        c.setFillColor(ink)
        c.drawString(M, yy, name)
        c.drawRightString(M + 230, yy, money(v))
        c.setStrokeColor(line_c)
        c.line(M, yy - 5, M + 230, yy - 5)
        yy -= 18

    x2 = M + 270
    c.setFont(bold, 11)
    c.drawString(x2, y2, lb["top_categories"])
    yy = y2 - 18
    palette = [primary, primary2, HexColor("#8FA898"), HexColor("#C2CFC5"), exp]
    for i, item in enumerate(data["expense_by_category"][:6]):
        c.setFillColor(palette[i % len(palette)])
        c.rect(x2, yy - 2, 8, 8, stroke=0, fill=1)
        c.setFillColor(ink)
        c.setFont(font, 9.5)
        c.drawString(x2 + 14, yy, item["name"][:24])
        c.drawRightString(W - M, yy, f"{money(item['amount'])} · {item['share']:.0f}%")
        yy -= 18

    # AI insight
    yy = min(yy, y2 - 18 * 6) - 24
    if insight:
        c.setFillColor(HexColor("#DDE6DF"))
        lines = _wrap(c, insight, font, 9.5, W - 2 * M - 24)[:8]
        box_h = 26 + 13 * len(lines)
        c.roundRect(M, yy - box_h + 14, W - 2 * M, box_h, 10, stroke=0, fill=1)
        c.setFillColor(primary)
        c.setFont(bold, 10)
        c.drawString(M + 12, yy, lb["ai"])
        c.setFillColor(ink)
        c.setFont(font, 9.5)
        for k, ln in enumerate(lines):
            c.drawString(M + 12, yy - 16 - k * 13, ln)
        yy -= box_h + 10

    c.setFillColor(muted)
    c.setFont(font, 7.5)
    for k, ln in enumerate(_wrap(c, DISCLAIMER["ru" if lang == "ru" else "uk"], font, 7.5, W - 2 * M)):
        c.drawString(M, 40 - k * 10, ln)
    c.drawRightString(W - M, 22, lb["generated"])
    c.showPage()
    c.save()
    return buf.getvalue()


def file_name(business: Business, start: date, end: date, ext: str) -> str:
    safe = "".join(ch for ch in business.name if ch.isalnum() or ch in " -_").strip().replace(" ", "_")[:40] or "finplan"
    return f"{safe}_{start:%Y-%m-%d}_{end:%Y-%m-%d}.{ext}"


__all__ = ["report_data", "excel_bytes", "pdf_bytes", "csv_bytes", "json"]
