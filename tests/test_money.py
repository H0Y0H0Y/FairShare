import pytest

from app.utils.money import format_cents, split_even, to_cents


def test_to_cents_int():
    assert to_cents(500) == 50000


def test_to_cents_decimal_string():
    assert to_cents("500.50") == 50050


def test_to_cents_thousands_separator():
    assert to_cents("1,234.5") == 123450


def test_to_cents_strips_currency_symbol():
    assert to_cents("₱500") == 50000


def test_to_cents_half_up_rounding():
    assert to_cents("0.125") == 13  # 12.5 cents -> 13


def test_to_cents_rejects_negative():
    with pytest.raises(ValueError):
        to_cents("-5")


def test_to_cents_rejects_garbage():
    with pytest.raises(ValueError):
        to_cents("abc")


def test_format_cents_with_symbol():
    assert format_cents(50000, "₱") == "₱500.00"


def test_format_cents_grouping():
    assert format_cents(123456) == "1,234.56"


def test_split_even_exact():
    assert split_even(70000, 2) == [35000, 35000]


def test_split_even_remainder_goes_to_first():
    parts = split_even(101, 2)
    assert parts == [51, 50]
    assert sum(parts) == 101
