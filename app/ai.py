"""AI assistant (spec section 8) on the Claude API with tool use.

* The model never writes to the database. Tools that change something (add_operation, add_debt,
  create_invoice) only create an AiDraft; a person presses "✅ Записать" and the server writes it
  through the same validation as the Mini App, with that person's role.
* Read tools (query_summary, list_operations, get_tax_status, find_counterparty) run with the
  asking member's rights and the plan's history window; the model only sees their results.
* The system prompt is stable and cached; the short business context comes after it.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import func, select

from . import finance, plans, services
from .config import get_settings
from .finance import q2
from .models import AiDraft, AiUsage, Business, Counterparty, Member, Operation

MAX_TOOL_ROUNDS = 6
# Models that accept the server-side refusal fallback (Claude API). Others are called without it.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You are the assistant inside finplan Business, a bookkeeping app for small businesses in Ukraine \
(FOP sole proprietors of groups 1-3, small shops, cafes, craftspeople, freelancers, small teams) that works in Telegram.

What you do:
1. Record operations from free text, receipt photos and voice transcripts. A message can hold several things \
("yesterday sold 3 cakes at 450 and bought packaging for 300, Olya owes me 200" = an income of 1350, an expense \
of 300 and a debt of 200). Call add_operation / add_debt / create_invoice once per item. These tools do not write \
anything: they create a draft the person confirms with a button. Never say something is saved; say what you prepared \
for confirmation.
2. Answer questions about the business's numbers with query_summary, list_operations, get_tax_status and \
find_counterparty. Use only numbers returned by tools; if a tool returns an error (for example the period is outside \
the plan's history), explain it plainly. Do not invent figures.
3. Give short, practical observations: what grew, what fell, what to look at.

Rules:
- Dates: resolve "today", "yesterday", "last week", month names against the current date given in the context. \
Use ISO dates (YYYY-MM-DD).
- Amounts: "3 по 450" means quantity 3 at 450 each, amount 1350. "12к" means 12000. Use the business currency \
unless another currency is named.
- Categories: pick the closest name from the business's category list; if nothing fits use null.
- Counterparties: use the name the person wrote; the server matches it with existing clients and suppliers.
- Receipt photos: one expense per receipt with the total, date and seller (as the counterparty); put the main \
items into the note. If the photo is not a receipt or invoice, say so.
- Taxes: you may explain the app's tax calculation, but say it is for reference and does not replace an accountant.
- Answer in the language of the person's message (Ukrainian or Russian, English if they write English). \
Be brief: a few short lines, no tables, no markdown headings. Format money like "12 400 ₴"."""

# ---------------------------------------------------------------- tools (strict JSON schemas)

NULLABLE_STR = {"type": ["string", "null"]}
NULLABLE_NUM = {"type": ["number", "null"]}

TOOLS = [
    {
        "name": "add_operation",
        "description": "Prepare an income or expense for the person to confirm. Nothing is saved until they confirm.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["income", "expense"]},
                "amount": {"type": "number", "description": "Total amount, positive."},
                "currency": {**NULLABLE_STR, "description": "ISO code like UAH, USD; null = business currency."},
                "date": {**NULLABLE_STR, "description": "YYYY-MM-DD; null = today."},
                "category": {**NULLABLE_STR, "description": "A category name from the business's list, or null."},
                "counterparty": {**NULLABLE_STR, "description": "Client or supplier name, or null."},
                "note": {**NULLABLE_STR, "description": "Short description, e.g. '3 торта'."},
            },
            "required": ["kind", "amount", "currency", "date", "category", "counterparty", "note"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_debt",
        "description": "Prepare a debt record for confirmation: someone owes the business (they_owe) or the business owes someone (we_owe).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["they_owe", "we_owe"]},
                "amount": {"type": "number"},
                "counterparty": {"type": "string"},
                "due_date": {**NULLABLE_STR, "description": "YYYY-MM-DD or null."},
                "note": NULLABLE_STR,
            },
            "required": ["direction", "amount", "counterparty", "due_date", "note"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_invoice",
        "description": "Prepare an invoice to a client for confirmation.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "counterparty": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}, "qty": {"type": "number"}, "price": {"type": "number"}},
                        "required": ["name", "qty", "price"],
                        "additionalProperties": False,
                    },
                },
                "due_date": {**NULLABLE_STR, "description": "YYYY-MM-DD; null = in 7 days."},
            },
            "required": ["counterparty", "items", "due_date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "query_summary",
        "description": "Revenue, expenses, profit, margin, number of sales and average check for a date range, "
                       "optionally grouped by category, client, project, member or month.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                "group_by": {"type": "string", "enum": ["none", "category", "client", "project", "member", "month"]},
            },
            "required": ["date_from", "date_to", "group_by"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_operations",
        "description": "List individual operations (newest first) with optional filters.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "date_from": NULLABLE_STR,
                "date_to": NULLABLE_STR,
                "kind": {"type": "string", "enum": ["any", "income", "expense", "transfer"]},
                "search": {**NULLABLE_STR, "description": "Text to find in notes or client names."},
                "limit": {**NULLABLE_NUM, "description": "Up to 50; null = 20."},
            },
            "required": ["date_from", "date_to", "kind", "search", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_tax_status",
        "description": "The FOP's upcoming tax payments (single tax, ESV, military levy) with deadlines, quarterly "
                       "taxes for the current year and the yearly income limit progress.",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "find_counterparty",
        "description": "Find clients or suppliers by (part of) name; returns their revenue and open debts.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
]
WRITE_TOOLS = {"add_operation", "add_debt", "create_invoice"}


class AiUnavailable(Exception):
    pass


@dataclass
class AiResult:
    text: str
    drafts: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    refused: bool = False


_client = None


def client():
    global _client
    key = get_settings().anthropic_api_key
    if not key:
        raise AiUnavailable("ANTHROPIC_API_KEY is not set")
    if _client is None:
        import anthropic
        _client = anthropic.AsyncAnthropic(api_key=key)
    return _client


def enabled() -> bool:
    return bool(get_settings().anthropic_api_key)


# ---------------------------------------------------------------- limits and usage

def month_key(today: date) -> str:
    return f"{today.year:04d}-{today.month:02d}"


async def requests_this_month(session, business: Business) -> int:
    key = month_key(finance.local_today(business.timezone))
    return int(await session.scalar(select(func.sum(AiUsage.requests)).where(
        AiUsage.business_id == business.id, AiUsage.month == key)) or 0)


async def check_quota(session, business: Business) -> dict:
    used = await requests_this_month(session, business)
    limit = plans.limits_for(business)["ai_requests"]
    if limit is not None and used >= limit:
        raise plans.upgrade_error(business, "ai_requests", limit)
    return {"used": used, "limit": limit}


async def record_usage(session, business: Business, member_id: int, requests: int, input_tokens: int,
                       output_tokens: int) -> None:
    key = month_key(finance.local_today(business.timezone))
    row = await session.scalar(select(AiUsage).where(AiUsage.business_id == business.id,
                                                     AiUsage.member_id == member_id, AiUsage.month == key))
    if row is None:
        row = AiUsage(business_id=business.id, member_id=member_id, month=key, requests=0, input_tokens=0, output_tokens=0)
        session.add(row)
    row.requests += requests
    row.input_tokens += input_tokens
    row.output_tokens += output_tokens


# ---------------------------------------------------------------- context

async def business_context(session, business: Business, member: Member) -> str:
    today = finance.local_today(business.timezone)
    cats = await services.categories(session, business.id)
    cps = (await session.scalars(select(Counterparty.name).where(Counterparty.business_id == business.id)
                                 .order_by(Counterparty.id.desc()).limit(60))).all()
    kind = {"fop": f"FOP group {business.fop_group}" if business.fop_group else "FOP", "company": "company (LLC)",
            "freelance": "freelancer"}[business.kind]
    return (f"Today: {today.isoformat()} ({today:%A}). Business: {business.name}, {kind}"
            f"{f', single tax {business.tax_rate:g}%' if business.fop_group == 3 else ''}, currency {business.currency}.\n"
            f"Person asking: {member.name or 'member'}, role {member.role}.\n"
            f"Income categories: {', '.join(c.name for c in cats if c.kind == 'income')}.\n"
            f"Expense categories: {', '.join(c.name for c in cats if c.kind == 'expense')}.\n"
            f"Known clients and suppliers: {', '.join(cps) if cps else 'none yet'}.")


# ---------------------------------------------------------------- tool execution

def _date(value, default: date | None = None) -> date | None:
    if not value:
        return default
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as error:
        raise ToolError(f"Bad date {value!r}, use YYYY-MM-DD") from error


def _amount(value) -> Decimal:
    try:
        amount = q2(Decimal(str(value)))
    except (InvalidOperation, ValueError) as error:
        raise ToolError("Amount must be a number") from error
    if amount <= 0:
        raise ToolError("Amount must be positive")
    return amount


class ToolError(Exception):
    pass


async def category_by_name(session, business_id: int, kind: str, name: str | None, note: str | None):
    cats = await services.categories(session, business_id, kind)
    if name:
        low = name.strip().lower()
        for c in cats:
            if c.name.lower() == low:
                return c
        for c in cats:
            if low[:5] and (low[:5] in c.name.lower() or c.name.lower()[:5] in low):
                return c
    key = finance.category_key_for(" ".join(filter(None, [name, note])))
    return await services.resolve_category(session, business_id, kind, key, note or "")


async def make_draft(session, business: Business, member: Member, action: str, data: dict) -> dict:
    """Validate and normalise a write tool's input into a pending AiDraft."""
    today = finance.local_today(business.timezone)
    if action == "add_operation":
        if not plans.can(member.role, "add_operation"):
            raise ToolError("This member's role cannot add operations")
        kind = data["kind"]
        cat = await category_by_name(session, business.id, kind, data.get("category"), data.get("note"))
        cp = await services.find_counterparty(session, business.id, data.get("counterparty") or "")
        day = _date(data.get("date"), today)
        if day > today + timedelta(days=366):
            raise ToolError("Date is too far in the future")
        payload = {"kind": kind, "amount": str(_amount(data["amount"])),
                   "currency": (data.get("currency") or business.currency).upper()[:3], "occurred_at": day.isoformat(),
                   "category_id": cat.id if cat else None, "category": cat.name if cat else None,
                   "counterparty_id": cp.id if cp else None,
                   "counterparty": cp.name if cp else (data.get("counterparty") or None), "note": data.get("note")}
    elif action == "add_debt":
        if not plans.can(member.role, "write"):
            raise ToolError("This member's role cannot add debts")
        cp = await services.find_counterparty(session, business.id, data["counterparty"])
        due = _date(data.get("due_date"))
        payload = {"direction": data["direction"], "amount": str(_amount(data["amount"])),
                   "counterparty_id": cp.id if cp else None, "counterparty": cp.name if cp else data["counterparty"],
                   "due_date": due.isoformat() if due else None, "note": data.get("note")}
    elif action == "create_invoice":
        if not plans.can(member.role, "write"):
            raise ToolError("This member's role cannot create invoices")
        from .documents import parse_items
        try:
            items = parse_items([{"name": i["name"], "qty": i["qty"], "price": i["price"]} for i in data["items"]])
        except HTTPException as error:
            raise ToolError(str(error.detail)) from error
        cp = await services.find_counterparty(session, business.id, data["counterparty"])
        due = _date(data.get("due_date"), today + timedelta(days=7))
        payload = {"items": items, "total": str(sum(Decimal(str(i["sum"])) for i in items)),
                   "counterparty_id": cp.id if cp else None, "counterparty": cp.name if cp else data["counterparty"],
                   "due_date": due.isoformat()}
    else:
        raise ToolError("Unknown action")
    draft = AiDraft(business_id=business.id, member_id=member.id, action=action, payload=json.dumps(payload, ensure_ascii=False))
    session.add(draft)
    await session.flush()
    return {"id": draft.id, "action": action, **payload}


def _ops_as_dicts(rows, names) -> list[dict]:
    return [{"date": o.occurred_at.isoformat(), "kind": o.kind, "amount": float(o.amount), "currency": o.currency,
             "category": names["cat"].get(o.category_id), "counterparty": names["cp"].get(o.counterparty_id),
             "note": o.note} for o in rows]


async def run_read_tool(session, business: Business, member: Member, name: str, data: dict) -> dict:
    today = finance.local_today(business.timezone)
    if not plans.can(member.role, "read") and name != "list_operations":
        raise ToolError("This member's role can only see their own operations")
    if name == "query_summary":
        start, end = _date(data["date_from"]), _date(data["date_to"])
        if end < start:
            start, end = end, start
        try:
            plans.check_history(business, start, today)
        except HTTPException as error:
            raise ToolError(f"The {plans.effective_plan(business)} plan shows history from "
                            f"{plans.history_start(business, today)}; Pro opens all history") from error
        from .reports import report_data
        d = await report_data(session, business, start, end)
        out = {"period": [start.isoformat(), end.isoformat()], "currency": business.currency,
               **{k: (float(v) if isinstance(v, Decimal) else v) for k, v in d["summary"].items()},
               "previous_period": [d["previous_start"].isoformat(), d["previous_end"].isoformat()],
               "previous": {k: float(d["previous"][k]) for k in ("revenue", "expenses", "profit")},
               "change_pct": {k: (float(v) if v is not None else None) for k, v in d["change"].items()}}
        group = data.get("group_by") or "none"
        if group == "category":
            out["income_by_category"] = [{"name": r["name"], "amount": float(r["amount"])} for r in d["income_by_category"]]
            out["expense_by_category"] = [{"name": r["name"], "amount": float(r["amount"])} for r in d["expense_by_category"]]
        elif group in ("client", "project", "member"):
            key = {"client": "by_client", "project": "by_project", "member": "by_member"}[group]
            out[key] = [{"name": r["name"], "revenue": float(r["amount"]), "sales": r["count"]} for r in d[key][:20]]
        elif group == "month":
            out["by_month"] = [{"month": m["month"], "income": float(m["income"]), "expense": float(m["expense"])}
                               for m in d["cashflow"] if start.strftime("%Y-%m") <= m["month"] <= end.strftime("%Y-%m")]
        return out
    if name == "list_operations":
        limit = int(min(max(data.get("limit") or 20, 1), 50))
        kind = data.get("kind")
        rows = await services.list_operations(session, business, member, kind=None if kind in (None, "any") else kind, q=data.get("search"),
                                              date_from=_date(data.get("date_from")), date_to=_date(data.get("date_to")),
                                              limit=limit)
        from .models import Category
        names = {"cat": dict((await session.execute(select(Category.id, Category.name).where(Category.business_id == business.id))).all()),
                 "cp": await services.counterparty_names(session, business.id)}
        return {"operations": _ops_as_dicts(rows, names), "history_from": str(plans.history_start(business, today) or "all")}
    if name == "get_tax_status":
        t = await services.tax_overview(session, business, today)
        if not t["applicable"]:
            return {"applicable": False, "reason": "Taxes are calculated for FOP groups 1-3 only."}
        return {"group": business.fop_group, "rate_pct": float(business.tax_rate),
                "upcoming": [{k: (v.isoformat() if isinstance(v, date) else float(v) if isinstance(v, Decimal) else v)
                              for k, v in p.items()} for p in t["upcoming"]],
                "quarters": [{"period": q["period"], "income": float(q["income_total"]), "single_tax": float(q["single_tax"]),
                              "military_levy": float(q["military_levy"]), "esv": float(q["esv"]), "status": q["status"]}
                             for q in t["quarters"] if not q.get("future")],
                "income_limit": {k: (float(v) if isinstance(v, Decimal) else v) for k, v in (t["limit"] or {}).items()},
                "note": "Reference calculation; not a substitute for an accountant."}
    if name == "find_counterparty":
        q = f"%{data['name'].strip().lower()}%"
        rows = (await session.scalars(select(Counterparty).where(Counterparty.business_id == business.id,
                                                                 func.lower(Counterparty.name).like(q)).limit(10))).all()
        out = []
        for c in rows:
            revenue = await session.scalar(select(func.sum(Operation.amount_base)).where(
                Operation.business_id == business.id, Operation.counterparty_id == c.id, Operation.kind == "income"))
            from .models import Debt
            debt = await session.scalar(select(func.sum(Debt.amount)).where(
                Debt.business_id == business.id, Debt.counterparty_id == c.id, Debt.status == "open",
                Debt.direction == "they_owe"))
            out.append({"name": c.name, "kind": c.kind, "phone": c.phone, "revenue_all_time": float(revenue or 0),
                        "owes_us": float(debt or 0)})
        return {"matches": out}
    raise ToolError(f"Unknown tool {name}")


async def execute_tool(session, business: Business, member: Member, name: str, data: dict, drafts: list) -> tuple[str, bool]:
    """Returns (JSON result for the model, is_error)."""
    try:
        if name in WRITE_TOOLS:
            draft = await make_draft(session, business, member, name, data)
            drafts.append(draft)
            return json.dumps({"draft_id": draft["id"], "status": "waiting for the person's confirmation",
                               "prepared": draft}, ensure_ascii=False, default=str), False
        return json.dumps(await run_read_tool(session, business, member, name, data), ensure_ascii=False, default=str), False
    except ToolError as error:
        return json.dumps({"error": str(error)}, ensure_ascii=False), True
    except (KeyError, TypeError, ValueError) as error:
        return json.dumps({"error": f"Invalid input: {error}"}, ensure_ascii=False), True


# ---------------------------------------------------------------- the conversation

def request_options(model: str) -> dict:
    opts: dict = {}
    if model in FALLBACK_MODELS:
        opts.update(betas=[FALLBACK_BETA], fallbacks="default")
    return opts


SORRY = {"ru": "Не получилось, попробуйте ещё раз.", "uk": "Не вийшло, спробуйте ще раз.", "en": "That didn't work, please try again."}
REFUSED = {"ru": "С этим я помочь не могу. Спросите о ваших продажах, расходах, налогах или запишите операцию.",
           "uk": "З цим я допомогти не можу. Запитайте про продажі, витрати, податки або запишіть операцію.",
           "en": "I can't help with that. Ask about your sales, expenses or taxes, or record an operation."}


async def ask(session, business: Business, member: Member, text: str, *, lang: str = "uk",
              history: list[dict] | None = None, image: tuple[bytes, str] | None = None) -> AiResult:
    """Run one assistant turn with tools. Raises AiUnavailable when no API key; HTTPException(402) over quota."""
    import anthropic

    api = client()
    await check_quota(session, business)
    settings = get_settings()
    model = settings.ai_model
    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
              {"type": "text", "text": await business_context(session, business, member)}]
    messages: list[dict] = []
    for turn in (history or [])[-8:]:
        if turn.get("role") in ("user", "assistant") and turn.get("text"):
            messages.append({"role": turn["role"], "content": str(turn["text"])[:2000]})
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    content: list[dict] = []
    if image:
        data, media_type = image
        content.append({"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                     "data": base64.standard_b64encode(data).decode()}})
    content.append({"type": "text", "text": text or "Запиши расход по этому чеку."})
    messages.append({"role": "user", "content": content})

    result = AiResult(text="")
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = await api.beta.messages.create(
                model=model, max_tokens=16000, system=system, tools=TOOLS, tool_choice={"type": "auto"},
                output_config={"effort": "medium"}, messages=messages, **request_options(model))
            result.input_tokens += (response.usage.input_tokens or 0) + (getattr(response.usage, "cache_read_input_tokens", 0) or 0)
            result.output_tokens += response.usage.output_tokens or 0
            if response.stop_reason == "refusal":
                result.text, result.refused = REFUSED.get(lang, REFUSED["uk"]), True
                break
            # Keep the assistant turn exactly as returned (thinking blocks must be passed back unchanged).
            messages.append({"role": "assistant", "content": response.content})
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            texts = [b.text for b in response.content if b.type == "text"]
            if response.stop_reason == "max_tokens" and tool_uses:
                result.text = SORRY.get(lang, SORRY["uk"])  # a cut-off tool call is never run
                break
            if response.stop_reason != "tool_use" or not tool_uses:
                result.text = "\n".join(t for t in texts if t).strip()
                break
            results = []
            for block in tool_uses:
                output, is_error = await execute_tool(session, business, member, block.name, dict(block.input), result.drafts)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output, "is_error": is_error})
            messages.append({"role": "user", "content": results})  # all results in one message
        else:
            result.text = result.text or SORRY.get(lang, SORRY["uk"])
    except anthropic.APIError:
        logging.exception("Claude API call failed")
        result.text = SORRY.get(lang, SORRY["uk"])
        result.drafts = []
    if not result.text and result.drafts:
        result.text = {"ru": "Проверьте и подтвердите:", "en": "Please check and confirm:"}.get(lang, "Перевірте й підтвердіть:")
    await record_usage(session, business, member.id, 1, result.input_tokens, result.output_tokens)
    return result


# ---------------------------------------------------------------- confirming drafts

async def confirm_draft(session, business: Business, member: Member, draft_id: int) -> dict:
    draft = await session.get(AiDraft, draft_id)
    if draft is None or draft.business_id != business.id:
        raise HTTPException(404, "Draft not found")
    if draft.status != "pending":
        raise HTTPException(409, "Already handled")
    if draft.member_id != member.id and not plans.can(member.role, "write"):
        raise HTTPException(403, "Only the person who asked can confirm this")
    p = json.loads(draft.payload)
    if draft.action == "add_operation":
        plans.require(member.role, "add_operation")
        cp_id = p.get("counterparty_id")
        if not cp_id and p.get("counterparty"):
            try:
                cp_id = (await services.get_or_create_counterparty(
                    session, business, p["counterparty"], "client" if p["kind"] == "income" else "supplier")).id
            except HTTPException:
                cp_id = None  # over the Free limit: keep the name in the note
                p["note"] = " · ".join(filter(None, [p.get("note"), p["counterparty"]]))
        op = await services.record_operation(session, business, member, kind=p["kind"], amount=Decimal(p["amount"]),
                                             currency=p.get("currency"), category_id=p.get("category_id"),
                                             counterparty_id=cp_id, note=p.get("note"),
                                             occurred_at=date.fromisoformat(p["occurred_at"]), source="ai",
                                             attachment_file_id=p.get("attachment_file_id"))
        draft.result_id = op.id
    elif draft.action == "add_debt":
        plans.require(member.role, "write")
        cp_id = p.get("counterparty_id") or (await services.get_or_create_counterparty(session, business, p["counterparty"])).id
        from .models import Debt
        debt = Debt(business_id=business.id, counterparty_id=cp_id, direction=p["direction"], amount=Decimal(p["amount"]),
                    due_date=date.fromisoformat(p["due_date"]) if p.get("due_date") else None, note=p.get("note"))
        session.add(debt)
        await session.flush()
        draft.result_id = debt.id
    elif draft.action == "create_invoice":
        plans.require(member.role, "write")
        cp_id = p.get("counterparty_id") or (await services.get_or_create_counterparty(session, business, p["counterparty"])).id
        from .documents import create_invoice
        inv = await create_invoice(session, business, counterparty_id=cp_id, items=p["items"],
                                   due_date=date.fromisoformat(p["due_date"]) if p.get("due_date") else None)
        draft.result_id = inv.id
    draft.status = "done"
    return {"id": draft.id, "status": "done", "action": draft.action, "result_id": draft.result_id}


async def reject_draft(session, business: Business, member: Member, draft_id: int) -> dict:
    draft = await session.get(AiDraft, draft_id)
    if draft is None or draft.business_id != business.id or draft.status != "pending":
        raise HTTPException(404, "Draft not found")
    if draft.member_id != member.id and not plans.can(member.role, "write"):
        raise HTTPException(403, "Only the person who asked can reject this")
    draft.status = "rejected"
    return {"id": draft.id, "status": "rejected"}


def draft_text(d: dict, lang: str, currency: str) -> str:
    money = lambda v, c=None: finance.money(Decimal(str(v)), c or currency)  # noqa: E731
    ru = lang == "ru"
    if d["action"] == "add_operation":
        sign = "+" if d["kind"] == "income" else "−"
        bits = [d.get("category"), d.get("counterparty"), d.get("note")]
        return (f"{'Доход' if ru and d['kind'] == 'income' else 'Расход' if ru else 'Дохід' if d['kind'] == 'income' else 'Витрата'} "
                f"{sign}{money(d['amount'], d.get('currency'))} · {date.fromisoformat(d['occurred_at']):%d.%m}"
                + ("\n" + " · ".join(b for b in bits if b) if any(bits) else ""))
    if d["action"] == "add_debt":
        who = d.get("counterparty") or "—"
        head = ("Долг: " if ru else "Борг: ") + (f"{who} должен(на) вам" if ru and d["direction"] == "they_owe" else
                                                f"вы должны {who}" if ru else f"{who} винен(на) вам"
                                                if d["direction"] == "they_owe" else f"ви винні {who}")
        return f"{head} {money(d['amount'])}" + (f" до {date.fromisoformat(d['due_date']):%d.%m}" if d.get("due_date") else "")
    items = ", ".join(f"{i['name']} × {i['qty']:g}" for i in d["items"])
    return (f"{'Счёт' if ru else 'Рахунок'} для {d.get('counterparty') or '—'}: {money(d['total'])}\n{items}")


# ---------------------------------------------------------------- weekly insight

async def weekly_insight(session, business: Business, start: date, end: date, lang: str) -> str | None:
    """One sentence for the weekly / monthly report. Uses AI_MODEL_FAST at low effort, no tools."""
    if not enabled():
        return None
    from .reports import report_data
    d = await report_data(session, business, start, end)
    if not d["summary"]["revenue"] and not d["summary"]["expenses"]:
        return None
    ps, pe = d["previous_start"], d["previous_end"]
    prev = await report_data(session, business, ps, pe)
    facts = {
        "period": f"{start}..{end}", "currency": business.currency,
        "now": {k: float(d["summary"][k]) for k in ("revenue", "expenses", "profit")},
        "before": {k: float(prev["summary"][k]) for k in ("revenue", "expenses", "profit")},
        "expenses_now": {r["name"]: float(r["amount"]) for r in d["expense_by_category"][:8]},
        "expenses_before": {r["name"]: float(r["amount"]) for r in prev["expense_by_category"][:8]},
        "top_clients": [r["name"] for r in d["by_client"][:3] if r["id"]],
    }
    language = {"ru": "Russian", "en": "English"}.get(lang, "Ukrainian")
    model = get_settings().fast_model
    try:
        response = await client().beta.messages.create(
            model=model, max_tokens=2000, output_config={"effort": "low"},
            system=f"You write one short, specific observation (max 25 words) for a small business owner about their "
                   f"week, in {language}, from the JSON facts only. Mention a concrete number or percent. No greetings.",
            messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False)}], **request_options(model))
    except Exception:
        logging.exception("Insight call failed")
        return None
    if response.stop_reason == "refusal":
        return None
    member = await session.scalar(select(Member).where(Member.business_id == business.id, Member.role == "owner"))
    if member:
        await record_usage(session, business, member.id, 0, response.usage.input_tokens or 0, response.usage.output_tokens or 0)
    text = " ".join(b.text for b in response.content if b.type == "text").strip()
    return text[:300] or None


def install() -> None:
    from . import jobs_money
    jobs_money.insight_provider = weekly_insight
