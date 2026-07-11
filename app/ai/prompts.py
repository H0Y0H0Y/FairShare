"""Prompt construction for the extraction and adjustment calls.

The models (a small Llama for text, Qwen-VL for images) must return a single
strict JSON object. Small models imitate concrete examples far more reliably
than abstract placeholders, so both prompts embed the *actual* partner names and
a fully-worked example built from them.
"""
from __future__ import annotations

import json


def _contract(partner1_name: str, partner2_name: str, today: str) -> str:
    """The JSON contract, specialized with the real partner names + an example."""
    example = {
        "description": "Lunch",
        "total": 450,
        "paid_by": partner1_name,
        "date": today,
        "shares": {partner1_name: 250, partner2_name: 200},
        "split_specified": True,
        "items": [
            {"name": "Caesar salad", "price": 250},
            {"name": "Iced coffee", "price": 200},
        ],
    }
    return f"""Return ONLY a single JSON object — no prose, no markdown, no code fences.

The JSON MUST have exactly these keys: "description", "total", "paid_by", \
"date", "shares", "split_specified", "items".

Hard rules:
- "description" is a SHORT label for WHAT this expense actually is — 1 to 3 words, \
derived from the message or receipt. It is NOT always food: it may be dining, \
groceries, transport, shopping, household, utilities, health, entertainment, or \
anything else. Examples across categories: "Lunch", "Groceries", "Taxi", \
"Movie tickets", "Pharmacy", "Fuel", "Electricity bill", "Hardware store". \
Pick the label that fits THIS transaction — do NOT copy "Lunch" from the example \
below unless the expense really is lunch. Do NOT include the venue name, address, \
location, or any person's name in the description.
- "paid_by" MUST be the literal string "{partner1_name}" or "{partner2_name}". \
Never invent a name, and never output a placeholder like "PERSON_NAME".
- "shares" MUST have exactly these two keys: "{partner1_name}" and "{partner2_name}". \
Values are numbers that add up to "total".
- The user usually states only ONE partner's share. In that case set the other \
partner's share to ("total" minus the stated share), and set "split_specified" true.
- "total" and share values are plain numbers — no currency symbols, no thousands \
separators.
- "date" is strict "YYYY-MM-DD". If no date is stated, use {today}.
- If NO split is stated at all, set "split_specified" false and split evenly.
- "items" is the list of individual line items when a receipt is present, each \
{{"name": short item name, "price": number}}. Read every line off the receipt. \
If there is no receipt or no itemized lines, use an empty list []. The item prices \
should add up to (or close to) "total"; never invent items that are not shown.
- Resolve "me"/"my"/"I paid" to the SENDER, and "you"/"your"/"yours" to the \
OTHER partner, then write the resolved real name.

Example of a valid response:
{json.dumps(example, ensure_ascii=False)}"""


def build_extraction_system_prompt(
    *, partner1_name: str, partner2_name: str, sender_name: str, today: str
) -> str:
    return f"""You extract a single shared expense from a message that may include \
text, a receipt image, or both.

The ONLY two people are "{partner1_name}" and "{partner2_name}".
The SENDER of this message is "{sender_name}".
Today's date is {today}.

If both an image and a text caption are provided, the caption takes priority for \
the split and amounts; use the image to fill in anything the caption omits (such \
as the total or a description).

When a receipt image is present, read the merchant name and line items to decide \
what the expense actually is, then write that as "description" (e.g. a grocery \
store -> "Groceries", a pharmacy -> "Pharmacy", a gas station -> "Fuel", a \
restaurant -> "Dinner"). Do NOT assume it is food.

{_contract(partner1_name, partner2_name, today)}"""


def build_merge_system_prompt(
    *, partner1_name: str, partner2_name: str, sender_name: str, today: str
) -> str:
    return f"""You are adjusting an existing draft expense using a short \
correction from the user.

The ONLY two people are "{partner1_name}" and "{partner2_name}".
The SENDER of the correction is "{sender_name}".
Today's date is {today}.

You will be given the CURRENT draft as JSON and a correction in natural language \
(e.g. "my share is 400", "paid by {partner2_name}", "date yesterday", \
"it was 720 total"). Apply ONLY the requested change; keep everything else the \
same. Re-balance the shares so they still sum to the total.

The draft may include an "items" list (the individual receipt lines with prices). \
Use it when the correction refers to items instead of amounts:
- "my share is the salad and the coffee" -> set the SENDER's share to the sum of \
those items' prices, and the OTHER partner's share to ("total" minus that sum).
- "split each item in half" / "go dutch" -> split the total 50/50.
- "you pay for the drinks, I'll cover the food" -> assign each named item's price \
to that partner and sum per partner.
Match item references loosely (case-insensitive, partial names). Keep the "items" \
list itself unchanged unless the correction explicitly edits an item.

{_contract(partner1_name, partner2_name, today)}"""


def build_merge_user_text(current_draft: dict, correction: str) -> str:
    return (
        "CURRENT draft:\n"
        + json.dumps(current_draft, ensure_ascii=False)
        + "\n\nCORRECTION:\n"
        + correction
    )
