"""The AI assistant in the bot: /ai, plain questions, receipt photos, voice messages, confirm buttons."""
from __future__ import annotations

import html
import io
import logging
import re

import httpx
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from fastapi import HTTPException

from . import ai, plans
from .bot import load
from .config import get_settings
from .database import SessionLocal
from .models import Business

router = Router(name="ai")

QUESTION_WORDS = ("сколько", "скільки", "какой", "какая", "какие", "який", "яка", "які", "почему", "чому", "как ", "як ",
                  "что ", "що ", "когда", "коли", "покажи", "порівняй", "сравни", "кто ", "хто ", "где", "де ")


def wants_ai(text: str) -> bool:
    """Questions and messages with several amounts go to the assistant; simple entries stay quick entries."""
    low = (text or "").strip().lower()
    if not low:
        return False
    if "?" in low or low.startswith(QUESTION_WORDS):
        return True
    numbers = re.findall(r"\d+(?:[.,]\d+)?", low)
    if len(numbers) > 2 or (len(numbers) == 2 and " по " not in f" {low} "):
        return True
    return len(low.split()) > 10


def t(lang: str, ru: str, uk: str) -> str:
    return ru if lang == "ru" else uk


def draft_keyboard(lang: str, draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "✅ Записать", "✅ Записати"), callback_data=f"aiok:{draft_id}"),
        InlineKeyboardButton(text=t(lang, "✏️ В приложении", "✏️ У застосунку"), callback_data=f"aied:{draft_id}"),
        InlineKeyboardButton(text="✖", callback_data=f"aino:{draft_id}")]])


async def run_assistant(message: Message, text: str, image: tuple[bytes, str] | None = None,
                        attachment: str | None = None) -> None:
    async with SessionLocal() as session:
        user, business, member = await load(session, message)
        lang = user.language
        if business is None:
            await session.commit()
            await message.answer("/start")
            return
        if not ai.enabled():
            await session.commit()
            await message.answer(t(lang, "ИИ-ассистент пока не настроен на сервере (нет ANTHROPIC_API_KEY).",
                                   "ШІ-асистент ще не налаштований на сервері (немає ANTHROPIC_API_KEY)."))
            return
        try:
            await message.bot.send_chat_action(message.chat.id, "typing")
        except Exception:
            pass
        try:
            result = await ai.ask(session, business, member, text, lang=lang, image=image)
        except HTTPException as error:
            await session.commit()
            if error.status_code == 402:
                limit = error.detail.get("limit") if isinstance(error.detail, dict) else None
                await message.answer(t(lang, f"Лимит ИИ на этот месяц исчерпан ({limit} запросов). Больше — в Pro/Team: /premium",
                                       f"Ліміт ШІ на цей місяць вичерпано ({limit} запитів). Більше — у Pro/Team: /premium"))
                return
            raise
        if attachment:
            import json
            from .models import AiDraft
            for d in result.drafts:
                row = await session.get(AiDraft, d["id"])
                payload = json.loads(row.payload)
                payload["attachment_file_id"] = attachment
                row.payload = json.dumps(payload, ensure_ascii=False)
        await session.commit()
        currency = business.currency
    if result.text:
        await message.answer(html.escape(result.text)[:4000])
    for d in result.drafts:
        await message.answer(html.escape(ai.draft_text(d, lang, currency)), reply_markup=draft_keyboard(lang, d["id"]))


async def answer_free_text(message: Message) -> None:
    await run_assistant(message, message.text or "")


@router.message(Command("ai"))
async def ai_cmd(message: Message, command: CommandObject) -> None:
    if command.args:
        await run_assistant(message, command.args)
        return
    async with SessionLocal() as session:
        user, _, _ = await load(session, message)
        await session.commit()
    await message.answer(t(user.language,
                           "Спросите что угодно о бизнесе или опишите операции словами:\n<i>сколько я заработал в октябре?</i>\n"
                           "<i>вчера продала 3 торта по 450 и купила упаковку на 300, Оля должна 200</i>\n"
                           "Можно прислать фото чека или голосовое.",
                           "Запитайте що завгодно про бізнес або опишіть операції словами:\n<i>скільки я заробив у жовтні?</i>\n"
                           "<i>вчора продала 3 торти по 450 і купила пакування на 300, Оля винна 200</i>\n"
                           "Можна надіслати фото чека або голосове."))


async def media_allowed(message: Message) -> tuple[bool, str]:
    async with SessionLocal() as session:
        user, business, _ = await load(session, message)
        await session.commit()
    if business is None:
        return False, user.language
    if not plans.limits_for(business)["media"]:
        await message.answer(t(user.language, "Фото чеков и голосовые — в Pro: /premium",
                               "Фото чеків і голосові — у Pro: /premium"))
        return False, user.language
    return True, user.language


async def download(bot: Bot, file_id: str) -> bytes:
    buf = io.BytesIO()
    await bot.download(file_id, destination=buf)
    return buf.getvalue()


@router.message(F.photo)
async def receipt_photo(message: Message) -> None:
    ok, lang = await media_allowed(message)
    if not ok:
        return
    photo = message.photo[-1]
    data = await download(message.bot, photo.file_id)
    caption = message.caption or t(lang, "Это чек или накладная. Запиши расход.", "Це чек або накладна. Запиши витрату.")
    await run_assistant(message, caption, image=(data, "image/jpeg"), attachment=photo.file_id)


async def transcribe(audio: bytes, filename: str = "voice.ogg") -> str | None:
    """Any OpenAI-compatible /audio/transcriptions endpoint (TRANSCRIPTION_API_URL + _KEY)."""
    s = get_settings()
    if not s.transcription_api_url:
        return None
    async with httpx.AsyncClient(timeout=60) as http:
        response = await http.post(s.transcription_api_url,
                                   headers={"Authorization": f"Bearer {s.transcription_api_key}"} if s.transcription_api_key else {},
                                   data={"model": s.transcription_model},
                                   files={"file": (filename, audio, "audio/ogg")})
        response.raise_for_status()
        return (response.json().get("text") or "").strip() or None


@router.message(F.voice | F.audio)
async def voice_message(message: Message) -> None:
    ok, lang = await media_allowed(message)
    if not ok:
        return
    media = message.voice or message.audio
    try:
        text = await transcribe(await download(message.bot, media.file_id))
    except Exception:
        logging.exception("Transcription failed")
        text = None
    if text is None:
        if not get_settings().transcription_api_url:
            await message.answer(t(lang, "Распознавание голоса не настроено на сервере (TRANSCRIPTION_API_URL).",
                                   "Розпізнавання голосу не налаштоване на сервері (TRANSCRIPTION_API_URL)."))
        else:
            await message.answer(t(lang, "Не удалось распознать голосовое, попробуйте текстом.",
                                   "Не вдалося розпізнати голосове, спробуйте текстом."))
        return
    await message.answer(f"🎙 <i>{html.escape(text)}</i>")
    await run_assistant(message, text)


@router.callback_query(F.data.startswith(("aiok:", "aino:", "aied:")))
async def draft_button(callback: CallbackQuery) -> None:
    action, raw = callback.data.split(":", 1)
    draft_id = int(raw)
    async with SessionLocal() as session:
        user, business, member = await load(session, callback)
        lang = user.language
        if business is None:
            await session.commit()
            await callback.answer()
            return
        if action == "aied":
            await session.commit()
            from .bot import app_keyboard
            await callback.answer()
            kb = app_keyboard(lang, "?tab=ai")
            await callback.message.answer(t(lang, "Откройте приложение — черновик в разделе ИИ.", "Відкрийте застосунок — чернетка в розділі ШІ."),
                                          reply_markup=kb)
            return
        try:
            if action == "aiok":
                await ai.confirm_draft(session, business, member, draft_id)
            else:
                await ai.reject_draft(session, business, member, draft_id)
            await session.commit()
        except HTTPException as error:
            await session.rollback()
            msg = error.detail if isinstance(error.detail, str) else (error.detail or {}).get("message", "")
            await callback.answer(msg[:180] or "—", show_alert=True)
            return
    done = t(lang, "✅ Записано", "✅ Записано") if action == "aiok" else t(lang, "Отменено", "Скасовано")
    await callback.answer(done)
    try:
        await callback.message.edit_text((callback.message.html_text or "") + f"\n<b>{done}</b>")
    except Exception:
        pass


__all__ = ["router", "Business"]
