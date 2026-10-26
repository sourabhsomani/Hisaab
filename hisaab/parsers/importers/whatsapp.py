"""Extract draft group expenses from an exported WhatsApp chat (.txt).

Understands lines like "paid 1200 for the cab", "₹600 dinner", "maine 500 diye petrol ke liye".
Every result is a *draft*: the user reviews it before it becomes an expense.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from dateutil import parser as dateparser

from hisaab.core.money import parse_amount

# Android: "24/10/26, 9:15 pm - Rahul: text"   iOS: "[24/10/26, 9:15:03 PM] Rahul: text"
_LINE = re.compile(
    r"^\[?(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),?\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*"
    r"(?:[ap]\.?\s?m\.?)?)\]?\s*(?:-\s*)?(?P<who>[^:]{1,60}):\s(?P<text>.*)$",
    re.IGNORECASE,
)
_AMT = r"(?:rs\.?|inr|₹)?\s*(?P<amt>\d[\d,]*(?:\.\d{1,2})?)\s*(?:rs|rupees|/-)?"
_PATTERNS = [
    re.compile(
        rf"(?i)\b(?:paid|spent|pay kiya|diye|de diye|bhara)\s+{_AMT}\s*"
        rf"(?:for|on|ka|ki|ke|ke liye)?\s*(?P<what>.*)"
    ),
    re.compile(
        rf"(?i)^(?:maine\s+)?{_AMT}\s+(?:paid|diye|de diye|spent)\s*"
        rf"(?:for|on|ka|ki|ke liye)?\s*(?P<what>.*)"
    ),
    re.compile(r"(?i)^(?:rs\.?|inr|₹)\s*(?P<amt>\d[\d,]*(?:\.\d{1,2})?)\s+(?:for\s+)?(?P<what>.+)"),
]
_FILLER = re.compile(r"(?i)\b(the|ke liye|ka|ki|ke|for|on|liye)\b")


@dataclass(frozen=True)
class ChatLine:
    at: datetime | None
    author: str
    text: str


@dataclass(frozen=True)
class ChatExpense:
    payer: str
    amount_paise: int
    description: str
    at: datetime | None
    source_line: str


def parse_lines(text: str) -> list[ChatLine]:
    """Split a chat export into messages; continuation lines join the previous message."""
    out: list[ChatLine] = []
    for raw in text.replace("‎", "").splitlines():
        m = _LINE.match(raw.strip())
        if m:
            try:
                at = dateparser.parse(f"{m['date']} {m['time'].replace('.', '')}", dayfirst=True)
            except (ValueError, OverflowError):
                at = None
            out.append(ChatLine(at, m["who"].strip(), m["text"].strip()))
        elif out and raw.strip():
            prev = out[-1]
            out[-1] = ChatLine(prev.at, prev.author, f"{prev.text} {raw.strip()}")
    return out


def clean_description(what: str) -> str:
    what = re.sub(r"[.!?]+$", "", what.strip())
    what = _FILLER.sub(" ", what)
    what = " ".join(what.split())
    return what[:60].capitalize() if what else "Expense"


def extract_expense(line: ChatLine) -> ChatExpense | None:
    """Return a draft expense if the message reports a payment."""
    if line.text.lower() in ("<media omitted>", "this message was deleted"):
        return None
    for pat in _PATTERNS:
        m = pat.search(line.text)
        if m:
            try:
                amount = parse_amount(m["amt"])
            except ValueError:
                continue
            if amount <= 0:
                continue
            return ChatExpense(
                line.author, amount, clean_description(m["what"]), line.at, line.text
            )
    return None


def parse_chat(text: str) -> list[ChatExpense]:
    """All draft expenses found in a WhatsApp chat export."""
    return [e for e in (extract_expense(ln) for ln in parse_lines(text)) if e]
