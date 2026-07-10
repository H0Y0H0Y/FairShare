"""Money helpers. Everything is stored and computed in integer minor units
(cents) to avoid floating-point drift when summing a ledger."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENTS = Decimal("0.01")


def to_cents(amount: float | int | str | Decimal) -> int:
    """Convert a human amount (e.g. ``500``, ``"500.50"``, ``"1,234.5"``) to
    integer cents. Raises ``ValueError`` on unparseable input."""
    if isinstance(amount, bool):  # bool is an int subclass; reject it explicitly
        raise ValueError("boolean is not a valid amount")
    if isinstance(amount, str):
        cleaned = amount.strip().replace(",", "").replace("_", "")
        # strip a leading currency symbol / stray non-numeric prefix chars
        cleaned = cleaned.lstrip("$€£₱¥ ")
        if not cleaned:
            raise ValueError("empty amount")
        try:
            dec = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"invalid amount: {amount!r}") from exc
    else:
        dec = Decimal(str(amount))

    if dec < 0:
        raise ValueError("amount must not be negative")
    cents = (dec * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def format_cents(cents: int, symbol: str = "") -> str:
    """Render integer cents as a grouped decimal string, e.g. 123456 → '1,234.56'."""
    sign = "-" if cents < 0 else ""
    value = Decimal(abs(cents)) / 100
    body = f"{value:,.2f}"
    prefix = f"{symbol}" if symbol else ""
    return f"{sign}{prefix}{body}"


def split_even(total_cents: int, n: int = 2) -> list[int]:
    """Split a total into ``n`` shares as evenly as possible. Any remainder cents
    are handed to the earliest shares so the parts always re-sum to the total."""
    if n <= 0:
        raise ValueError("n must be positive")
    base, remainder = divmod(total_cents, n)
    return [base + (1 if i < remainder else 0) for i in range(n)]
