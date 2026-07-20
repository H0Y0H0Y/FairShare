"""Domain models shared across layers.

Money is always represented in integer minor units (cents) once it crosses out
of the parsing layer, so nothing downstream deals with floats.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class LineItem:
    """A single itemized line read off a receipt. Kept on the draft so item-level
    corrections ("my share is the salad and the coffee", "split each item in
    half") can be resolved during the adjust step."""

    name: str
    price_cents: int


@dataclass
class ExpenseDraft:
    """A parsed-but-uncommitted expense, held in ``context.user_data`` during the
    confirm/adjust flow. Lives only in memory until the user confirms."""

    description: str
    total_cents: int
    paid_by: int  # partner id (1 or 2)
    expense_date: str  # strict 'YYYY-MM-DD'
    shares: dict[int, int]  # {partner_id: share_cents}, must sum to total_cents
    raw_input: str = ""
    # True when the AI did not give an explicit split and we defaulted to 50/50.
    split_inferred: bool = False
    # Itemized receipt lines, when parsed from an image. Empty for text entries.
    line_items: list[LineItem] = field(default_factory=list)

    def shares_sum(self) -> int:
        return sum(self.shares.values())

    def is_balanced(self) -> bool:
        return self.shares_sum() == self.total_cents

    def copy(self) -> "ExpenseDraft":
        return replace(self, shares=dict(self.shares), line_items=list(self.line_items))


@dataclass(frozen=True)
class Balance:
    """Net position over open expenses, expressed from partner 1's perspective.

    ``net_cents`` > 0  → partner 2 owes partner 1.
    ``net_cents`` < 0  → partner 1 owes partner 2.
    """

    partner1_id: int
    partner2_id: int
    net_cents: int  # signed, partner-1 perspective

    @property
    def creditor_id(self) -> int | None:
        if self.net_cents > 0:
            return self.partner1_id
        if self.net_cents < 0:
            return self.partner2_id
        return None

    @property
    def debtor_id(self) -> int | None:
        if self.net_cents > 0:
            return self.partner2_id
        if self.net_cents < 0:
            return self.partner1_id
        return None

    @property
    def magnitude_cents(self) -> int:
        return abs(self.net_cents)

    def may_confirm_settle(self, partner_id: int) -> bool:
        """Whether ``partner_id`` is allowed to confirm a settlement.

        Only the creditor — the partner who is owed — can confirm, since they're
        the one acknowledging the money actually reached them. When it's all
        square (no creditor), either partner may close things out.
        """
        return self.creditor_id is None or partner_id == self.creditor_id


@dataclass(frozen=True)
class RecentExpense:
    """A read-model row for the /recent listing."""

    id: int
    description: str
    total_cents: int
    paid_by: int
    expense_date: str
    shares: dict[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class OpenSummary:
    """Everything the /summary command shows: the open ledger, per-partner totals,
    and the resulting net balance."""

    items: list[RecentExpense]
    paid: dict[int, int]  # partner_id -> total paid (cents) over open expenses
    owed: dict[int, int]  # partner_id -> total of own shares (cents) over open
    balance: Balance
