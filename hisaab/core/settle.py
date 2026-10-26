"""Net balances and debt simplification.

balance_m = Σ paid_m − Σ share_m + Σ settled_out_m − Σ settled_in_m

A positive balance means the group owes that member; negative means the member owes.
"""

from __future__ import annotations

import heapq
from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)


@dataclass(frozen=True)
class Payment(Generic[K]):
    """``payer`` should send ``amount_paise`` to ``payee``."""

    payer: K
    payee: K
    amount_paise: int


def net_balances(
    paid: Iterable[tuple[K, int]],
    shares: Iterable[tuple[K, int]],
    settlements: Iterable[tuple[K, K, int]] = (),
    members: Iterable[K] = (),
) -> dict[K, int]:
    """Compute each member's net balance in paise.

    ``paid``: (payer, amount) per expense. ``shares``: (member, share) per expense share.
    ``settlements``: (from, to, amount) for confirmed repayments. ``members`` makes sure
    members with no activity still appear with 0.
    """
    bal: dict[K, int] = dict.fromkeys(members, 0)
    for m, amt in paid:
        bal[m] = bal.get(m, 0) + amt
    for m, amt in shares:
        bal[m] = bal.get(m, 0) - amt
    for frm, to, amt in settlements:
        bal[frm] = bal.get(frm, 0) + amt
        bal[to] = bal.get(to, 0) - amt
    return bal


def simplify_debts(balances: dict[K, int]) -> list[Payment[K]]:
    """Greedy settlement: largest debtor pays largest creditor until everyone is at zero.

    Produces at most n − 1 payments. Ties break by member order for stable output.
    """
    if sum(balances.values()) != 0:
        raise ValueError(f"balances do not sum to zero (off by {sum(balances.values())} paise)")
    order = {k: i for i, k in enumerate(balances)}
    creditors = [(-v, order[k], k) for k, v in balances.items() if v > 0]
    debtors = [(v, order[k], k) for k, v in balances.items() if v < 0]
    heapq.heapify(creditors)
    heapq.heapify(debtors)
    payments: list[Payment[K]] = []
    while creditors and debtors:
        c_neg, c_ord, c = heapq.heappop(creditors)
        d_neg, d_ord, d = heapq.heappop(debtors)
        credit, debt = -c_neg, -d_neg
        amount = min(credit, debt)
        payments.append(Payment(payer=d, payee=c, amount_paise=amount))
        if credit > amount:
            heapq.heappush(creditors, (-(credit - amount), c_ord, c))
        if debt > amount:
            heapq.heappush(debtors, (-(debt - amount), d_ord, d))
    return payments


def apply_payments(balances: dict[K, int], payments: Iterable[Payment[K]]) -> dict[K, int]:
    """Return balances after the given payments are made (used to verify settlement)."""
    out = dict(balances)
    for p in payments:
        out[p.payer] = out.get(p.payer, 0) + p.amount_paise
        out[p.payee] = out.get(p.payee, 0) - p.amount_paise
    return out


def debts_for(payments: Iterable[Payment[K]], member: K) -> tuple[int, int]:
    """(owed_by_member, owed_to_member) in paise across a payment plan."""
    payments = list(payments)
    owes = sum(p.amount_paise for p in payments if p.payer == member)
    gets = sum(p.amount_paise for p in payments if p.payee == member)
    return owes, gets
