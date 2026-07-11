"""Turn a user message (text and/or receipt image) into a validated
``ExpenseDraft``.

Flow: build payload -> call model -> extract JSON (with one repair retry) ->
resolve partner names & amounts -> return a draft. Amounts leave this module as
integer cents; names leave as partner ids.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime

from app.ai.client import get_client
from app.ai.prompts import (
    build_extraction_system_prompt,
    build_merge_system_prompt,
    build_merge_user_text,
)
from app.ai.router import pick_model
from app.config import PartnerConfig, get_settings
from app.models import ExpenseDraft, LineItem
from app.utils.money import split_even, to_cents

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3


class ParseError(Exception):
    """Raised when the model output cannot be turned into a valid draft."""


# --------------------------------------------------------------------------- #
# Model I/O
# --------------------------------------------------------------------------- #
async def _call_model(system: str, content: list[dict], model: str) -> str:
    """Call the model, retrying transient upstream failures (rate limits, a
    provider that fails over to a broken one) with a short backoff."""
    client = get_client()
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = await client.chat.completions.create(
                model=model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001 — provider errors vary; retry them all
            last_exc = exc
            log.warning("model call failed (attempt %d/%d): %s", attempt + 1, _MAX_ATTEMPTS, exc)
            if attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(1.5 * (attempt + 1))
    raise last_exc  # exhausted retries


def _extract_json(raw: str) -> dict:
    """Pull the first JSON object out of the model's reply."""
    match = _JSON_OBJECT_RE.search(raw)
    if not match:
        raise ParseError("no JSON object found in model output")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON: {exc}") from exc


async def _call_and_parse(system: str, content: list[dict], model: str) -> dict:
    """Call the model and parse JSON, with a single strict repair retry."""
    raw = await _call_model(system, content, model)
    try:
        return _extract_json(raw)
    except ParseError:
        repair = content + [
            {
                "type": "text",
                "text": "Your previous reply was not valid JSON. "
                "Reply with ONLY the JSON object, nothing else.",
            }
        ]
        raw = await _call_model(system, repair, model)
        return _extract_json(raw)


# --------------------------------------------------------------------------- #
# Resolution helpers
# --------------------------------------------------------------------------- #
def _resolve_partner_id(raw: str, sender: PartnerConfig, other: PartnerConfig) -> int:
    token = str(raw).strip().lower()
    if token in {"me", "myself", "i", "mine", sender.name.lower()}:
        return sender.id
    # Pronouns / relative references for the OTHER partner. Useful when the
    # partner's name gets scrubbed by an upstream PII filter and can't be typed.
    if token in {
        "you", "your", "yours", "partner", "them", "they", "their",
        "she", "her", "hers", "he", "him", "his", "the other", "other",
        other.name.lower(),
    }:
        return other.id
    # Substring match either way (handles "paid by Mark V", "mark's share", etc.).
    for p in (sender, other):
        name = p.name.lower()
        if name and (name in token or token in name):
            return p.id
    raise ParseError(f"could not resolve partner name: {raw!r}")


def _parse_line_items(raw: object) -> list[LineItem]:
    """Pull an itemized receipt list out of the model output. Best-effort: any
    entry without a usable name and price is skipped rather than failing the
    whole parse (the items are an aid for splitting, not core to the expense)."""
    if not isinstance(raw, list):
        return []
    items: list[LineItem] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()[:100]
        if not name:
            continue
        try:
            price_cents = to_cents(entry.get("price"))
        except (ValueError, TypeError):
            continue
        items.append(LineItem(name=name, price_cents=price_cents))
    return items


def _valid_date(value: object, today: str) -> str:
    if isinstance(value, str):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            pass
    return today


def _dict_to_draft(
    data: dict, sender: PartnerConfig, other: PartnerConfig, today: str, raw_input: str
) -> ExpenseDraft:
    if "total" not in data:
        raise ParseError("model output missing 'total'")

    total_cents = to_cents(data["total"])
    if total_cents <= 0:
        raise ParseError("total must be positive")

    description = str(data.get("description") or "Expense").strip()[:200]
    expense_date = _valid_date(data.get("date"), today)
    try:
        paid_by = _resolve_partner_id(data.get("paid_by", sender.name), sender, other)
    except ParseError:
        paid_by = sender.id  # default to the person who logged it

    split_specified = bool(data.get("split_specified"))
    shares: dict[int, int] = {}
    raw_shares = data.get("shares") or {}
    if split_specified and isinstance(raw_shares, dict) and raw_shares:
        items = list(raw_shares.items())
        # The prompt fixes the key order as (partner1, partner2), so if the model
        # emits unresolvable/placeholder keys we can still map them positionally.
        partners_in_order = get_settings().partners
        for idx, (name, amount) in enumerate(items):
            try:
                pid = _resolve_partner_id(name, sender, other)
            except ParseError:
                if len(items) == 2 and idx < len(partners_in_order):
                    pid = partners_in_order[idx].id
                else:
                    shares = {}
                    break
            shares[pid] = shares.get(pid, 0) + to_cents(amount)

    inferred = False
    # Fall back to an even split if the model gave no usable/balanced split.
    if set(shares.keys()) != {sender.id, other.id} or sum(shares.values()) != total_cents:
        s_sender, s_other = split_even(total_cents, 2)
        shares = {sender.id: s_sender, other.id: s_other}
        inferred = True  # we had to reconcile the split; ask the user to review

    return ExpenseDraft(
        description=description,
        total_cents=total_cents,
        paid_by=paid_by,
        expense_date=expense_date,
        shares=shares,
        raw_input=raw_input,
        split_inferred=inferred,
        line_items=_parse_line_items(data.get("items")),
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
async def parse_expense(
    *,
    text: str | None,
    image_b64: str | None,
    image_media_type: str,
    sender: PartnerConfig,
    today: str | None = None,
) -> ExpenseDraft:
    """Parse a fresh expense from text and/or an image. The image and caption are
    bundled into a SINGLE model request."""
    settings = get_settings()
    other = settings.other_partner(sender.id)
    today = today or date.today().isoformat()
    caption = (text or "").strip()

    content: list[dict] = []
    # Always include a text block so the model has an instruction anchor.
    content.append(
        {
            "type": "text",
            "text": caption or "Extract the expense from the attached receipt image.",
        }
    )
    if image_b64:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{image_media_type};base64,{image_b64}"},
            }
        )

    system = build_extraction_system_prompt(
        partner1_name=settings.partners[0].name,
        partner2_name=settings.partners[1].name,
        sender_name=sender.name,
        today=today,
    )
    model = pick_model(has_image=bool(image_b64))
    data = await _call_and_parse(system, content, model)

    raw_input = caption if not image_b64 else (f"[image] {caption}".strip())
    return _dict_to_draft(data, sender, other, today, raw_input)


async def merge_expense(
    *,
    current: ExpenseDraft,
    correction: str,
    sender: PartnerConfig,
    today: str | None = None,
) -> ExpenseDraft:
    """Apply a natural-language correction to an existing draft (text model)."""
    settings = get_settings()
    other = settings.other_partner(sender.id)
    today = today or date.today().isoformat()

    # Present the current draft to the model using partner NAMES, not ids.
    current_view = {
        "description": current.description,
        "total": current.total_cents / 100,
        "paid_by": settings.partner_by_id(current.paid_by).name,
        "date": current.expense_date,
        "shares": {
            settings.partner_by_id(pid).name: cents / 100
            for pid, cents in current.shares.items()
        },
        "split_specified": True,
    }
    # Carry the itemized receipt lines so a correction can reference them
    # ("my share is the salad and the coffee", "split each item in half").
    if current.line_items:
        current_view["items"] = [
            {"name": item.name, "price": item.price_cents / 100}
            for item in current.line_items
        ]

    system = build_merge_system_prompt(
        partner1_name=settings.partners[0].name,
        partner2_name=settings.partners[1].name,
        sender_name=sender.name,
        today=today,
    )
    content = [{"type": "text", "text": build_merge_user_text(current_view, correction)}]
    data = await _call_and_parse(system, content, settings.text_model)

    draft = _dict_to_draft(data, sender, other, today, current.raw_input)
    # Keep the receipt items across corrections; the text model often omits them
    # from its reply even when they still apply to the expense.
    if not draft.line_items and current.line_items:
        draft.line_items = list(current.line_items)
    return draft
