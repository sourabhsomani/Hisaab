"""Money helpers. All amounts inside Hisaab are integer paise (1 rupee = 100 paise)."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_CURRENCY = re.compile(r"(?i)(?:(?:rs|inr)\.?|₹)\s*")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?|\.\d+")


def to_paise(rupees: Decimal | int | float | str) -> int:
    """Convert a rupee value to integer paise, rounding half up.

    >>> to_paise("450.5")
    45050
    """
    try:
        value = Decimal(str(rupees))
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {rupees!r}") from exc
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_amount(text: str) -> int:
    """Parse an Indian amount string such as ``Rs.1,23,456.00`` or ``INR 450`` into paise.

    Raises ``ValueError`` when no number is present.
    """
    if text is None:
        raise ValueError("amount is empty")
    cleaned = _CURRENCY.sub("", text.strip())
    match = _NUMBER.search(cleaned)
    if not match:
        raise ValueError(f"no amount in {text!r}")
    return to_paise(match.group(0).replace(",", ""))


def group_indian(digits: str) -> str:
    """Insert Indian-system commas into a string of digits: ``123456`` -> ``1,23,456``."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return ",".join(pairs) + "," + tail


def format_inr(paise: int, symbol: bool = True) -> str:
    """Format paise as ``₹1,23,456.00`` using the Indian numbering system."""
    sign = "-" if paise < 0 else ""
    rupees, rem = divmod(abs(int(paise)), 100)
    body = f"{group_indian(str(rupees))}.{rem:02d}"
    return f"{sign}{'₹' if symbol else ''}{body}"


def paise_to_decimal_str(paise: int) -> str:
    """Plain ``450.00`` form used in UPI links (no symbol, no commas)."""
    if paise < 0:
        raise ValueError("UPI amounts cannot be negative")
    rupees, rem = divmod(int(paise), 100)
    return f"{rupees}.{rem:02d}"
