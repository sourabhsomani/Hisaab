"""Stage 4: block re-imports by hash and merge the bank + UPI-app SMS for one payment."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import timedelta

from hisaab.parsers.types import ParsedTxn

WINDOW = timedelta(minutes=3)


def message_hash(sender: str | None, body: str) -> str:
    """Stable hash of a message; whitespace and case changes do not matter."""
    norm = re.sub(r"\s+", " ", body).strip().lower()
    key = f"{(sender or '').strip().upper()}|{norm}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def is_same_payment(a: ParsedTxn, b: ParsedTxn, window: timedelta = WINDOW) -> bool:
    """Same UPI reference, or same amount + direction + account tail within ``window``."""
    if a.upi_ref and b.upi_ref:
        return a.upi_ref == b.upi_ref
    if a.amount_paise != b.amount_paise or a.direction != b.direction:
        return False
    if not (a.account_tail and b.account_tail and a.account_tail == b.account_tail):
        return False
    if a.txn_at is None or b.txn_at is None:
        return False
    midnight = a.txn_at.replace(hour=0, minute=0, second=0).time()
    if a.txn_at.time() == midnight or b.txn_at.time() == midnight:
        # at least one SMS only carried a date: the same day counts as inside the window
        return a.txn_at.date() == b.txn_at.date()
    return abs(a.txn_at - b.txn_at) <= window


def merge(primary: ParsedTxn, other: ParsedTxn) -> ParsedTxn:
    """Fill gaps in ``primary`` with fields from ``other``; keep the higher confidence."""
    out = primary.copy()
    for name in (
        "account_tail",
        "counterparty_name",
        "counterparty_vpa",
        "upi_ref",
        "txn_at",
        "balance_paise",
        "merchant",
        "bank",
    ):
        if getattr(out, name) is None and getattr(other, name) is not None:
            setattr(out, name, getattr(other, name))
    out.confidence = max(primary.confidence, other.confidence)
    return out


def dedupe(txns: Iterable[ParsedTxn], window: timedelta = WINDOW) -> tuple[list[ParsedTxn], int]:
    """Collapse duplicate payments. Returns (unique transactions, number merged away)."""
    kept: list[ParsedTxn] = []
    merged = 0
    for t in txns:
        for i, k in enumerate(kept):
            if is_same_payment(k, t, window):
                kept[i] = merge(k, t)
                merged += 1
                break
        else:
            kept.append(t)
    return kept, merged
