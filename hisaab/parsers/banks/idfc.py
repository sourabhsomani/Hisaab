"""IDFC FIRST Bank. Senders: AX-IDFCFB, VM-IDFCFB."""

from hisaab.parsers.banks._base import P, match_first
from hisaab.parsers.types import ParsedTxn

BANK = "IDFC FIRST Bank"
SENDERS = ["IDFCFB", "IDFCBK"]

PATTERNS = [
    # Your A/C XXXXXXX2211 is debited by INR 899.00 on 24/10/26 21:10. New Bal :INR 4,101.00.
    # UPI Ref 429877771111 to netflix@ybl. -IDFC FIRST Bank
    P(
        r"A/C\s*X*(?P<acct>\d{4})\s+is\s+(?P<dir>debited|credited)\s+by\s+INR\s*"
        r"(?P<amount>[\d,]+(?:\.\d+)?)\s+on\s+(?P<date>[\d/]+\s+[\d:]+)\.\s*New Bal\s*:INR\s*"
        r"(?P<bal>[\d,]+(?:\.\d+)?)\.\s*UPI Ref\s*(?P<ref>\d+)\s+(?:to|from)\s+(?P<name>\S+?)\.\s"
    ),
]


def parse(body: str) -> ParsedTxn | None:
    return match_first(body, PATTERNS, BANK)
