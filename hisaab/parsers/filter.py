"""Stage 1: keep bank transaction SMS.

Rejects OTPs, promotions, due-date reminders, mandate setups, payment requests and failures.
"""

from __future__ import annotations

import re

# DLT sender headers look like AX-HDFCBK, JD-SBIUPI, VM-ICICIT-S
_DLT = re.compile(r"^[A-Z]{2}-[A-Z0-9]{3,9}(?:-[A-Z])?$")

_TXN_WORDS = re.compile(
    r"(?i)\b(debited|credited|sent|received|spent|paid|withdrawn|transferred|deposited|"
    r"debit|credit)\b"
)

_REJECT: list[tuple[str, re.Pattern[str]]] = [
    ("otp", re.compile(r"(?i)\b(otp|one[- ]time password|verification code|do not share)\b")),
    (
        "failed",
        re.compile(
            r"(?i)\b(failed|declined|unsuccessful|could not be processed|"
            r"has been rejected|not successful)\b"
        ),
    ),
    (
        "request",
        re.compile(
            r"(?i)(has requested|requested money|collect request|"
            r"request(?:ed)? (?:for )?(?:rs\.?|inr|₹))"
        ),
    ),
    (
        "mandate",
        re.compile(
            r"(?i)(mandate (?:is )?(?:created|registered|set ?up|successfully)|"
            r"autopay (?:is )?(?:set ?up|activated|registered)|e-?mandate request)"
        ),
    ),
    (
        "reminder",
        re.compile(
            r"(?i)(\bdue (?:on|date|by)\b|minimum (?:amount )?due|"
            r"payment reminder|bill (?:is )?(?:generated|due)|total due)"
        ),
    ),
    (
        "promo",
        re.compile(
            r"(?i)(pre-?approved|apply now|\boffer\b|cashback (?:of )?up ?to|"
            r"\bloan\b.*\b(?:avail|eligible)|click here to claim|limited period)"
        ),
    ),
]


def is_bank_sender(sender: str | None) -> bool:
    """True for DLT headers. Empty senders (pasted SMS) are allowed through."""
    if not sender:
        return True
    return bool(_DLT.match(sender.strip().upper()))


def reject_reason(body: str) -> str | None:
    """Name of the first reject rule the body hits, or ``None``."""
    for name, pattern in _REJECT:
        if pattern.search(body):
            return name
    return None


def has_transaction_words(body: str) -> bool:
    return bool(_TXN_WORDS.search(body))


def classify_message(sender: str | None, body: str) -> tuple[bool, str]:
    """Return (keep, reason). ``reason`` explains a rejection, or is ``"ok"``."""
    if not body or not body.strip():
        return False, "empty"
    if not is_bank_sender(sender):
        return False, "not_bank_sender"
    reason = reject_reason(body)
    if reason:
        return False, reason
    if not has_transaction_words(body):
        return False, "no_transaction"
    return True, "ok"
