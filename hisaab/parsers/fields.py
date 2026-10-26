"""Field extractors shared by the generic parser and bank plugins."""

from __future__ import annotations

import re
from datetime import datetime

from dateutil import parser as dateparser

from hisaab.core.models import Direction
from hisaab.core.money import parse_amount

AMOUNT_RE = re.compile(r"(?i)(?:rs\.?|inr\.?|₹)\s*([\d,]*\d(?:\.\d{1,2})?)")
_VERB_AMOUNT = re.compile(
    r"(?i)\b(?:debited|credited|sent|paid|received|spent|withdrawn)\s+(?:by|with|for|of)?\s*"
    r"(?:rs\.?|inr\.?|₹)?\s*([\d,]*\d(?:\.\d{1,2})?)"
)
_DEBIT = re.compile(r"(?i)\b(debited|debit|sent|spent|paid|withdrawn|purchase|transferred to)\b")
_CREDIT = re.compile(r"(?i)\b(credited|credit|received|deposited|refund(?:ed)?)\b")
_ACCOUNT = re.compile(
    r"(?i)\b(?:a/?c|acct|account|card)(?:\s*no\.?)?\s*(?:ending|ending with)?\s*"
    r"[*xX.]*\s*(\d{3,6})\b"
)
_VPA = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9.\-_]*@[A-Za-z][A-Za-z0-9]{1,63})\b")
_REF = re.compile(
    r"(?i)\b(?:upi\s*ref(?:erence)?(?:\s*no)?|ref(?:\s*no)?|refno|rrn|utr|txn\s*id)\b"
    r"[.:#\s]*(\d{9,14})"
)
_BALANCE = re.compile(
    r"(?i)\b(?:avl\.?\s*bal(?:ance)?|available\s+bal(?:ance)?|a/c\s*bal|bal)\b[.:\s]*"
    r"(?:is\s*)?(?:rs\.?|inr\.?|₹)?\s*([\d,]*\d(?:\.\d{1,2})?)"
)
_DATE = re.compile(
    r"(?i)\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{1,2}[- ]?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|"
    r"oct|nov|dec)[a-z]*[- ,]?\d{2,4}|\d{4}-\d{2}-\d{2})"
    r"(?:[ ,:T]*(?:at\s*)?(\d{1,2}:\d{2}(?::\d{2})?\s*(?:[ap]m)?))?"
)
_NAME_STOP = (
    r"(?=\s+(?:on|ref|refno|upi|via|at|for|from|to|using|avl|bal|not|if|info|txn|is)\b|"
    r"\s*[.(\-,;]|\s*$)"
)
_COUNTERPARTY = re.compile(
    r"(?i)\b(?:trf to|transferred to|paid to|sent to|to|from|by|transfer from)\s+(?:vpa\s+)?"
    r"(?!a/?c\b|your\b|you\b|ac\b|account\b)"
    r"([A-Za-z][A-Za-z.&' ]{1,40}?)" + _NAME_STOP
)
_MERCHANT = re.compile(
    r"(?i)\b(?:at|towards|info:?)\s+([A-Za-z0-9*][A-Za-z0-9*&.' \-]{1,40}?)" + _NAME_STOP
)


def find_amount(body: str) -> int | None:
    """First currency-marked amount, falling back to 'debited by 450.00' style."""
    for pat in (AMOUNT_RE, _VERB_AMOUNT):
        m = pat.search(body)
        if m:
            try:
                value = parse_amount(m.group(1))
            except ValueError:
                continue
            if value > 0:
                return value
    return None


def find_direction(body: str) -> Direction | None:
    """Whichever of debit/credit keywords appears first wins."""
    d, c = _DEBIT.search(body), _CREDIT.search(body)
    if d and (not c or d.start() < c.start()):
        return Direction.DEBIT
    if c:
        return Direction.CREDIT
    return None


def find_account_tail(body: str) -> str | None:
    m = _ACCOUNT.search(body)
    return m.group(1)[-4:] if m else None


def find_vpa(body: str) -> str | None:
    m = _VPA.search(body)
    return m.group(1).lower() if m else None


def find_ref(body: str) -> str | None:
    m = _REF.search(body)
    return m.group(1) if m else None


def find_balance(body: str) -> int | None:
    m = _BALANCE.search(body)
    if not m:
        return None
    try:
        return parse_amount(m.group(1))
    except ValueError:
        return None


def parse_sms_date(text: str) -> datetime | None:
    """Parse Indian SMS dates: 24/10/26, 24-10-2026, 25Oct26, 25-Oct-26, 2026-10-25, + time."""
    m = _DATE.search(text)
    if not m:
        return None
    raw_date, raw_time = m.group(1), m.group(2)
    compact = re.fullmatch(r"(?i)(\d{1,2})([a-z]{3})[a-z]*(\d{2,4})", raw_date.replace(" ", ""))
    if compact:
        raw_date = f"{compact.group(1)} {compact.group(2)} {compact.group(3)}"
    iso = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date))
    try:
        dt = dateparser.parse(raw_date, dayfirst=not iso, yearfirst=iso)
    except (ValueError, OverflowError):
        return None
    if raw_time:
        try:
            t = dateparser.parse(raw_time)
            dt = dt.replace(hour=t.hour, minute=t.minute, second=t.second)
        except (ValueError, OverflowError):
            pass
    return dt.replace(tzinfo=None, microsecond=0)


def clean_name(name: str | None) -> str | None:
    if not name:
        return None
    name = re.sub(r"\s+", " ", name).strip(" .-'&")
    return name or None


def find_counterparty(body: str) -> str | None:
    for m in _COUNTERPARTY.finditer(body):
        name = clean_name(m.group(1))
        if name and not re.fullmatch(r"(?i)(the|your|you|a/?c|ac|upi|bank|imps|neft|vpa)", name):
            return name
    return None


def find_merchant(body: str) -> str | None:
    m = _MERCHANT.search(body)
    return clean_name(m.group(1)) if m else None
