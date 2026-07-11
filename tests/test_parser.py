import pytest

from app.ai import parser
from app.config import get_settings

pytestmark = pytest.mark.asyncio


def _sender():
    return get_settings().partners[0]  # Mark, id=1


def _patch_model(monkeypatch, replies):
    """Make ``_call_model`` return canned strings in sequence."""
    seq = list(replies)

    async def fake_call_model(system, content, model):
        return seq.pop(0)

    monkeypatch.setattr(parser, "_call_model", fake_call_model)


async def test_parse_text_with_explicit_split(monkeypatch):
    _patch_model(
        monkeypatch,
        [
            '{"description":"Dinner","total":700,"paid_by":"Mark",'
            '"date":"2026-07-10","shares":{"Mark":500,"Alex":200},'
            '"split_specified":true}'
        ],
    )
    draft = await parser.parse_expense(
        text="Dinner 700, my share 500, yours 200",
        image_b64=None,
        image_media_type="image/jpeg",
        sender=_sender(),
        today="2026-07-10",
    )
    assert draft.total_cents == 70000
    assert draft.paid_by == 1
    assert draft.shares == {1: 50000, 2: 20000}
    assert draft.expense_date == "2026-07-10"
    assert draft.is_balanced()
    assert draft.split_inferred is False


async def test_parse_resolves_me_and_yours(monkeypatch):
    _patch_model(
        monkeypatch,
        [
            '{"description":"Groceries","total":300,"paid_by":"me",'
            '"date":"2026-07-10","shares":{"me":100,"yours":200},'
            '"split_specified":true}'
        ],
    )
    draft = await parser.parse_expense(
        text="groceries 300, my share 100, yours 200",
        image_b64=None,
        image_media_type="image/jpeg",
        sender=_sender(),
        today="2026-07-10",
    )
    assert draft.paid_by == 1
    assert draft.shares == {1: 10000, 2: 20000}


async def test_parse_defaults_to_even_split_when_unspecified(monkeypatch):
    _patch_model(
        monkeypatch,
        [
            '{"description":"Taxi","total":250,"paid_by":"Alex",'
            '"date":"2026-07-10","shares":{},"split_specified":false}'
        ],
    )
    draft = await parser.parse_expense(
        text="taxi 250 paid by alex",
        image_b64=None,
        image_media_type="image/jpeg",
        sender=_sender(),
        today="2026-07-10",
    )
    assert draft.paid_by == 2
    assert draft.shares == {1: 12500, 2: 12500}
    assert draft.split_inferred is True
    assert draft.is_balanced()


async def test_parse_repairs_bad_json(monkeypatch):
    _patch_model(
        monkeypatch,
        [
            "Sure! Here you go, no JSON at all.",
            '{"description":"Coffee","total":120,"paid_by":"Mark",'
            '"date":"2026-07-10","shares":{"Mark":60,"Alex":60},'
            '"split_specified":true}',
        ],
    )
    draft = await parser.parse_expense(
        text="coffee 120",
        image_b64=None,
        image_media_type="image/jpeg",
        sender=_sender(),
        today="2026-07-10",
    )
    assert draft.total_cents == 12000
    assert draft.shares == {1: 6000, 2: 6000}


async def test_parse_raises_when_both_replies_bad(monkeypatch):
    _patch_model(monkeypatch, ["nope", "still nope"])
    with pytest.raises(parser.ParseError):
        await parser.parse_expense(
            text="coffee 120",
            image_b64=None,
            image_media_type="image/jpeg",
            sender=_sender(),
            today="2026-07-10",
        )


async def test_parse_invalid_date_falls_back_to_today(monkeypatch):
    _patch_model(
        monkeypatch,
        [
            '{"description":"Lunch","total":400,"paid_by":"Mark",'
            '"date":"not-a-date","shares":{"Mark":200,"Alex":200},'
            '"split_specified":true}'
        ],
    )
    draft = await parser.parse_expense(
        text="lunch 400",
        image_b64=None,
        image_media_type="image/jpeg",
        sender=_sender(),
        today="2026-07-10",
    )
    assert draft.expense_date == "2026-07-10"


async def test_parse_reads_receipt_line_items(monkeypatch):
    _patch_model(
        monkeypatch,
        [
            '{"description":"Groceries","total":450,"paid_by":"Mark",'
            '"date":"2026-07-10","shares":{"Mark":225,"Alex":225},'
            '"split_specified":false,'
            '"items":[{"name":"Caesar salad","price":250},'
            '{"name":"Iced coffee","price":200}]}'
        ],
    )
    draft = await parser.parse_expense(
        text=None,
        image_b64="ZmFrZQ==",
        image_media_type="image/jpeg",
        sender=_sender(),
        today="2026-07-10",
    )
    assert [(i.name, i.price_cents) for i in draft.line_items] == [
        ("Caesar salad", 25000),
        ("Iced coffee", 20000),
    ]


async def test_parse_skips_malformed_items(monkeypatch):
    _patch_model(
        monkeypatch,
        [
            '{"description":"Groceries","total":250,"paid_by":"Mark",'
            '"date":"2026-07-10","shares":{"Mark":125,"Alex":125},'
            '"split_specified":false,'
            '"items":[{"name":"Milk","price":250},{"name":"","price":100},'
            '{"name":"Bad","price":"n/a"},"not-a-dict"]}'
        ],
    )
    draft = await parser.parse_expense(
        text=None,
        image_b64="ZmFrZQ==",
        image_media_type="image/jpeg",
        sender=_sender(),
        today="2026-07-10",
    )
    assert [(i.name, i.price_cents) for i in draft.line_items] == [("Milk", 25000)]


async def test_explicit_description_extraction():
    assert parser._explicit_description("description Marugame") == "Marugame"
    assert parser._explicit_description("desc: Marugame Udon") == "Marugame Udon"
    assert parser._explicit_description("call it Marugame") == "Marugame"
    assert parser._explicit_description("name it 7-Eleven") == "7-Eleven"
    assert parser._explicit_description('rename to "Groceries"') == "Groceries"
    # Guards: split phrases, multi-intent, and unrelated corrections are ignored.
    assert parser._explicit_description("call it even") is None
    assert parser._explicit_description("call it Marugame, my share 300") is None
    assert parser._explicit_description("my share is 400") is None


async def test_merge_forces_explicit_description_over_model(monkeypatch):
    """User renames to a venue; the model (per its no-venue-name rule) returns a
    generic "Lunch" — the deterministic override must win."""
    from app.models import ExpenseDraft

    current = ExpenseDraft(
        description="Lunch",
        total_cents=45000,
        paid_by=1,
        expense_date="2026-07-10",
        shares={1: 22500, 2: 22500},
    )
    _patch_model(
        monkeypatch,
        [
            '{"description":"Lunch","total":450,"paid_by":"Mark",'
            '"date":"2026-07-10","shares":{"Mark":225,"Alex":225},'
            '"split_specified":true}'
        ],
    )
    updated = await parser.merge_expense(
        current=current,
        correction="description Marugame",
        sender=_sender(),
        today="2026-07-10",
    )
    assert updated.description == "Marugame"


async def test_merge_applies_item_based_split(monkeypatch):
    """User references items ('the salad'); the model returns an item-based split
    and drops the items list from its reply — parser must keep the items."""
    from app.models import ExpenseDraft, LineItem

    current = ExpenseDraft(
        description="Lunch",
        total_cents=45000,
        paid_by=1,
        expense_date="2026-07-10",
        shares={1: 22500, 2: 22500},
        line_items=[
            LineItem(name="Caesar salad", price_cents=25000),
            LineItem(name="Iced coffee", price_cents=20000),
        ],
    )
    _patch_model(
        monkeypatch,
        [
            '{"description":"Lunch","total":450,"paid_by":"Mark",'
            '"date":"2026-07-10","shares":{"Mark":250,"Alex":200},'
            '"split_specified":true}'
        ],
    )
    updated = await parser.merge_expense(
        current=current,
        correction="my share is just the salad",
        sender=_sender(),
        today="2026-07-10",
    )
    assert updated.shares == {1: 25000, 2: 20000}
    # Items survive the correction even though the model omitted them.
    assert [i.name for i in updated.line_items] == ["Caesar salad", "Iced coffee"]
