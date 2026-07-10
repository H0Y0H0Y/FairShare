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
