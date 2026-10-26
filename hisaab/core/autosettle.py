"""Auto-settle: match an incoming credit SMS to a friend's pending debt.

A match needs the amount within ₹1 (or less, as a partial payment) and the sender to match
the member's UPI ID exactly, or their name/alias with a fuzzy score of at least 85. The
result is only a *proposal*; the user always confirms it.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from hisaab.core.models import Direction
from hisaab.parsers.types import ParsedTxn

AMOUNT_TOLERANCE = 100  # paise (₹1)
NAME_THRESHOLD = 85
VPA_SCORE = 100.0


@dataclass(frozen=True)
class Identity:
    """What a bank might print for a member."""

    member_id: Hashable
    name: str
    vpa: str | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Debt:
    """``debtor`` owes ``creditor`` (the user) ``amount_paise`` in ``group_id``."""

    debtor: Hashable
    creditor: Hashable
    amount_paise: int
    group_id: Hashable = None


@dataclass(frozen=True)
class Proposal:
    debt: Debt
    amount_paise: int
    score: float
    partial: bool


def _norm(text: str) -> str:
    return " ".join(text.upper().replace(".", " ").split())


def name_score(printed: str | None, identity: Identity) -> float:
    """Best fuzzy score of the printed name against the member's name and aliases."""
    if not printed:
        return 0.0
    target = _norm(printed)
    candidates = [identity.name, *identity.aliases]
    return max((fuzz.WRatio(target, _norm(c)) for c in candidates if c), default=0.0)


def identity_score(txn: ParsedTxn, identity: Identity) -> float:
    """100 for an exact UPI ID match, otherwise the fuzzy name score."""
    vpa, mine = txn.counterparty_vpa, identity.vpa
    if vpa and mine and vpa.lower() == mine.lower():
        return VPA_SCORE
    return float(name_score(txn.counterparty_name, identity))


def amount_fit(received: int, owed: int) -> tuple[bool, bool]:
    """(matches, partial). Within ₹1 is a full match; less is partial; more is no match."""
    if abs(received - owed) <= AMOUNT_TOLERANCE:
        return True, False
    if 0 < received < owed:
        return True, True
    return False, False


def match_credit(
    txn: ParsedTxn,
    debts: Iterable[Debt],
    identities: Iterable[Identity],
    threshold: float = NAME_THRESHOLD,
) -> Proposal | None:
    """Best proposal for one credit transaction, or ``None``.

    Ranking: full matches before partial, then higher identity score, then closest amount.
    """
    if txn.direction is not Direction.CREDIT:
        return None
    by_id = {i.member_id: i for i in identities}
    best: tuple[tuple, Proposal] | None = None
    for debt in debts:
        ident = by_id.get(debt.debtor)
        if ident is None:
            continue
        score = identity_score(txn, ident)
        if score < threshold:
            continue
        ok, partial = amount_fit(txn.amount_paise, debt.amount_paise)
        if not ok:
            continue
        amount = txn.amount_paise if partial else debt.amount_paise
        prop = Proposal(debt, amount, score, partial)
        key = (not partial, score, -abs(txn.amount_paise - debt.amount_paise))
        if best is None or key > best[0]:
            best = (key, prop)
    return best[1] if best else None
