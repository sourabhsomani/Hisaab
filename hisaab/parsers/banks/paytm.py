"""Paytm Payments Bank and the Paytm app. Senders: VM-PAYTMB, AX-PYTMBK, JD-iPaytm."""

from hisaab.core.models import Direction
from hisaab.parsers.banks._base import P, match_first
from hisaab.parsers.types import ParsedTxn

BANK = "Paytm"
SENDERS = ["PAYTMB", "PYTMBK", "IPAYTM", "PAYTM"]
D, C = Direction.DEBIT, Direction.CREDIT

PATTERNS = [
    # Paid Rs.85 to Chai Point from Paytm Payments Bank a/c XX9900. UPI Ref:429888881111.
    P(
        r"Paid\s+Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+to\s+(?P<name>.+?)\s+from Paytm Payments "
        r"Bank a/c\s*X*(?P<acct>\d{4})\.\s*UPI Ref:?\s*(?P<ref>\d+)",
        D,
    ),
    # Received Rs.450 in your a/c XX9900 from RAHUL KUMAR. UPI Ref: 429888882222 -PPBL
    P(
        r"Received\s+Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+in your a/c\s*X*(?P<acct>\d{4})\s+"
        r"from\s+(?P<name>.+?)\.\s*UPI Ref:?\s*(?P<ref>\d+)",
        C,
    ),
    # You paid Rs.450.00 to RAHUL KUMAR. UPI Ref No 429812345678
    P(
        r"You paid\s+Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+to\s+(?P<name>.+?)\.\s*UPI Ref(?: No)?"
        r":?\s*(?P<ref>\d+)",
        D,
    ),
]


def parse(body: str) -> ParsedTxn | None:
    return match_first(body, PATTERNS, BANK)
