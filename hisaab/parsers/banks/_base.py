"""Helpers for bank plugins. A plugin only lists its patterns; this module builds ParsedTxn.

Named groups a pattern may use:
``amount`` (required), ``dir`` (debit/credit words, when the pattern is not fixed),
``acct``, ``name``, ``vpa``, ``ref``, ``date``, ``bal``, ``merchant``.
Fields the pattern does not capture are filled from the generic extractors.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from hisaab.core.models import Direction
from hisaab.core.money import parse_amount
from hisaab.parsers import fields
from hisaab.parsers.types import ParsedTxn

BANK_CONFIDENCE = 0.95


@dataclass(frozen=True)
class Pattern:
    regex: re.Pattern[str]
    direction: Direction | None = None


def P(regex: str, direction: Direction | None = None) -> Pattern:  # noqa: N802 - tiny DSL
    """Compile a case-insensitive pattern for a bank plugin."""
    return Pattern(re.compile(regex, re.IGNORECASE), direction)


def _group(m: re.Match[str], name: str) -> str | None:
    try:
        value = m.group(name)
    except IndexError:
        return None
    return value.strip() if value else None


def direction_from_word(word: str | None) -> Direction | None:
    if not word:
        return None
    return fields.find_direction(word)


def build(
    body: str,
    m: re.Match[str],
    bank: str,
    direction: Direction | None,
    confidence: float = BANK_CONFIDENCE,
) -> ParsedTxn | None:
    """Turn a regex match into a ParsedTxn, filling gaps with generic extractors."""
    direction = direction or direction_from_word(_group(m, "dir"))
    raw_amount = _group(m, "amount")
    if direction is None or raw_amount is None:
        return None
    try:
        amount = parse_amount(raw_amount)
    except ValueError:
        return None
    name = fields.clean_name(_group(m, "name"))
    vpa = _group(m, "vpa")
    if name and "@" in name and not vpa:
        name, vpa = None, name
    acct = _group(m, "acct")
    date_text = _group(m, "date")
    bal = _group(m, "bal")
    return ParsedTxn(
        direction=direction,
        amount_paise=amount,
        account_tail=acct[-4:] if acct else fields.find_account_tail(body),
        counterparty_name=name,
        counterparty_vpa=(vpa.lower() if vpa else fields.find_vpa(body)),
        upi_ref=_group(m, "ref") or fields.find_ref(body),
        txn_at=fields.parse_sms_date(date_text) if date_text else fields.parse_sms_date(body),
        balance_paise=parse_amount(bal) if bal else fields.find_balance(body),
        merchant=fields.clean_name(_group(m, "merchant")),
        bank=bank,
        confidence=confidence,
    )


def match_first(body: str, patterns: Sequence[Pattern], bank: str) -> ParsedTxn | None:
    """Try each pattern in order and build the first match."""
    for pat in patterns:
        m = pat.regex.search(body)
        if m:
            txn = build(body, m, bank, pat.direction)
            if txn is not None:
                return txn
    return None
