"""Stage 2 fallback: bank-agnostic extraction when no bank plugin matches."""

from __future__ import annotations

from hisaab.parsers import fields
from hisaab.parsers.types import ParsedTxn

GENERIC_MAX_CONFIDENCE = 0.85


def score(txn: ParsedTxn, base: float = 0.45) -> float:
    """Confidence grows with every field we managed to extract."""
    s = base
    s += 0.1 if txn.txn_at else 0
    s += 0.1 if txn.account_tail else 0
    s += 0.1 if (txn.counterparty_name or txn.counterparty_vpa or txn.merchant) else 0
    s += 0.1 if txn.upi_ref else 0
    return round(min(s, 1.0), 2)


def parse(body: str) -> ParsedTxn | None:
    """Extract a transaction from any bank's SMS, or ``None`` if amount/direction are missing."""
    amount = fields.find_amount(body)
    direction = fields.find_direction(body)
    if amount is None or direction is None:
        return None
    txn = ParsedTxn(
        direction=direction,
        amount_paise=amount,
        account_tail=fields.find_account_tail(body),
        counterparty_vpa=fields.find_vpa(body),
        counterparty_name=fields.find_counterparty(body),
        upi_ref=fields.find_ref(body),
        txn_at=fields.parse_sms_date(body),
        balance_paise=fields.find_balance(body),
        merchant=fields.find_merchant(body),
        bank=None,
    )
    txn.confidence = min(score(txn), GENERIC_MAX_CONFIDENCE)
    return txn
