"""Stage 3 API: the AI assistant, drafts, bank connections, operation photos."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import ai, banks, plans, runtime, services
from .api import need
from .auth import Ctx, get_ctx
from .models import BankConnection, Operation

router = APIRouter(prefix="/api")


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


@router.get("/ai/usage")
async def ai_usage(ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = ctx.need_business()
    used = await ai.requests_this_month(ctx.session, business)
    return {"enabled": ai.enabled(), "used": used, "limit": plans.limits_for(business)["ai_requests"]}


@router.post("/ai/chat")
async def ai_chat(body: ChatIn, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, member = ctx.need_business()
    plans.require(member.role, "read_own")
    try:
        result = await ai.ask(ctx.session, business, member, body.message, lang=ctx.user.language,
                              history=[t.model_dump() for t in body.history])
    except ai.AiUnavailable as error:
        raise HTTPException(503, "The AI assistant is not configured on the server (ANTHROPIC_API_KEY)") from error
    await ctx.session.commit()
    used = await ai.requests_this_month(ctx.session, business)
    return {"text": result.text, "refused": result.refused,
            "drafts": [{**d, "text": ai.draft_text(d, ctx.user.language, business.currency)} for d in result.drafts],
            "usage": {"used": used, "limit": plans.limits_for(business)["ai_requests"]}}


@router.post("/ai/drafts/{draft_id}/{action}")
async def ai_draft(draft_id: int, action: Literal["confirm", "reject"], ctx: Ctx = Depends(get_ctx)) -> dict:
    business, member = ctx.need_business()
    if action == "confirm":
        out = await ai.confirm_draft(ctx.session, business, member, draft_id)
    else:
        out = await ai.reject_draft(ctx.session, business, member, draft_id)
    await ctx.session.commit()
    return out


# ---------------------------------------------------------------- banks

@router.get("/banks")
async def bank_list(ctx: Ctx = Depends(get_ctx)) -> list[dict]:
    business, _ = need(ctx, "read")
    rows = (await ctx.session.scalars(select(BankConnection).where(BankConnection.business_id == business.id))).all()
    return [banks.connection_dict(c) for c in rows]


class MonoToken(BaseModel):
    token: str = Field(min_length=20, max_length=200)


@router.post("/banks/mono/accounts")
async def mono_accounts(body: MonoToken, ctx: Ctx = Depends(get_ctx)) -> list[dict]:
    """List the person's monobank accounts so they can pick the FOP one. The token is not stored here."""
    business, _ = need(ctx, "manage")
    plans.require_feature(business, "banks")
    try:
        return await banks.mono_accounts(body.token.strip())
    except banks.BankError as error:
        raise HTTPException(502, str(error)) from error


class MonoConnect(MonoToken):
    account_external_id: str = Field(min_length=1, max_length=128)
    account_label: str = Field(default="monobank", max_length=120)
    account_id: int | None = None


@router.post("/banks/mono")
async def mono_connect(body: MonoConnect, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    plans.require_feature(business, "banks")
    account_id = await banks.ensure_account(ctx.session, business, "mono", body.account_label, body.account_id)
    conn = BankConnection(business_id=business.id, bank="mono", token_encrypted=banks.encrypt(body.token.strip()),
                          account_external_id=body.account_external_id, account_label=body.account_label,
                          account_id=account_id)
    ctx.session.add(conn)
    await ctx.session.flush()
    imported = await banks.sync(ctx.session, business, conn)
    await ctx.session.commit()
    return {**banks.connection_dict(conn), "imported": imported}


class PrivatConnect(BaseModel):
    client_id: str = Field(min_length=3, max_length=200)
    token: str = Field(min_length=10, max_length=500)
    iban: str = Field(min_length=15, max_length=34)
    account_id: int | None = None


@router.post("/banks/privat")
async def privat_connect(body: PrivatConnect, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    plans.require_feature(business, "banks")
    label = f"ПриватБанк {body.iban[-4:]}"
    account_id = await banks.ensure_account(ctx.session, business, "privat", label, body.account_id)
    conn = BankConnection(business_id=business.id, bank="privat", token_encrypted=banks.encrypt(body.token.strip()),
                          client_id_encrypted=banks.encrypt(body.client_id.strip()), account_external_id=body.iban.strip(),
                          account_label=label, account_id=account_id)
    ctx.session.add(conn)
    await ctx.session.flush()
    imported = await banks.sync(ctx.session, business, conn)
    await ctx.session.commit()
    return {**banks.connection_dict(conn), "imported": imported}


@router.post("/banks/{conn_id}/sync")
async def bank_sync(conn_id: int, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "write")
    plans.require_feature(business, "banks")
    conn = await services.owned(ctx.session, BankConnection, business.id, conn_id, required=True)
    imported = await banks.sync(ctx.session, business, conn, manual=True)
    await ctx.session.commit()
    return {**banks.connection_dict(conn), "imported": imported}


@router.delete("/banks/{conn_id}")
async def bank_delete(conn_id: int, ctx: Ctx = Depends(get_ctx)) -> dict:
    business, _ = need(ctx, "manage")
    conn = await services.owned(ctx.session, BankConnection, business.id, conn_id, required=True)
    await ctx.session.delete(conn)  # imported operations stay
    await ctx.session.commit()
    return {"ok": True}


# ---------------------------------------------------------------- receipt photo of an operation

@router.post("/operations/{op_id}/photo")
async def send_operation_photo(op_id: int, ctx: Ctx = Depends(get_ctx)) -> dict:
    """Send the receipt photo stored with an operation to the person's bot chat."""
    business, member = ctx.need_business()
    op = await services.owned(ctx.session, Operation, business.id, op_id, required=True)
    if member.role == "staff" and op.member_id != member.id:
        raise HTTPException(403, "Not allowed")
    if not op.attachment_file_id:
        raise HTTPException(404, "No photo")
    try:
        await runtime.require_bot().send_photo(ctx.user.telegram_id, op.attachment_file_id, caption=op.note or None)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(502, "Could not send the photo to the bot chat") from error
    return {"ok": True}
