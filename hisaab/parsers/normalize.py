"""Stage 3: strip gateway prefixes and merge merchant spellings."""

from __future__ import annotations

import re
from functools import lru_cache

from hisaab.core.models import Direction
from hisaab.data import load_json
from hisaab.parsers.types import ParsedTxn

_GATEWAY = re.compile(
    r"(?i)^(?:(?:raz|pyu|ptm|cf|bdk|ccav|pp)\*|(?:razorpay|payu|paytm|cashfree|billdesk|"
    r"phonepe|gpay|google pay)\s*[*\-:]\s*)"
)
_SUFFIX = re.compile(
    r"(?i)[\s,]+(?:pvt\.?|private|ltd\.?|limited|llp|inc\.?|india|technologies|retail|"
    r"services|co\.?)\b\.?"
)


def strip_gateway_prefix(name: str) -> str:
    """``RAZ*SWIGGY`` -> ``SWIGGY``; ``PAYTM-Zomato`` -> ``Zomato``."""
    prev = None
    while prev != name:
        prev, name = name, _GATEWAY.sub("", name.strip())
    return name.strip()


def strip_company_suffix(name: str) -> str:
    """``Swiggy Pvt Ltd`` -> ``Swiggy``."""
    prev = None
    while prev != name:
        prev, name = name, _SUFFIX.sub("", name).strip()
    return name


@lru_cache(maxsize=1)
def merchant_map() -> dict[str, dict]:
    return load_json("merchants.json")


def canonical_merchant(name: str | None, merchants: dict[str, dict] | None = None) -> str | None:
    """Map any spelling to its brand name using keyword containment; else a cleaned name."""
    if not name:
        return None
    merchants = merchants if merchants is not None else merchant_map()
    cleaned = strip_gateway_prefix(name)
    low = cleaned.lower()
    for brand, info in merchants.items():
        if any(re.search(rf"\b{re.escape(k)}", low) for k in info.get("keywords", [])):
            return brand
    base = strip_company_suffix(cleaned)
    return base.title() if base.isupper() or base.islower() else base or None


def known_brand(name: str | None, merchants: dict[str, dict] | None = None) -> bool:
    merchants = merchants if merchants is not None else merchant_map()
    return bool(name) and name in merchants


def normalize_txn(txn: ParsedTxn, merchants: dict[str, dict] | None = None) -> ParsedTxn:
    """Clean names and pick a merchant for debits (brand from name, merchant or UPI handle)."""
    merchants = merchants if merchants is not None else merchant_map()
    name = strip_gateway_prefix(txn.counterparty_name) if txn.counterparty_name else None
    merchant = txn.merchant
    if txn.direction is Direction.DEBIT:
        for candidate in (txn.merchant, name, (txn.counterparty_vpa or "").split("@")[0]):
            brand = canonical_merchant(candidate, merchants) if candidate else None
            if brand and known_brand(brand, merchants):
                merchant = brand
                break
        else:
            merchant = canonical_merchant(txn.merchant, merchants) if txn.merchant else None
    return txn.copy(counterparty_name=name or None, merchant=merchant)
