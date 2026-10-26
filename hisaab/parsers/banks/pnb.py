"""Punjab National Bank. Senders: AX-PNBSMS, VM-PNBSMS."""

from hisaab.parsers.banks._base import P, match_first
from hisaab.parsers.types import ParsedTxn

BANK = "PNB"
SENDERS = ["PNBSMS", "PNBBNK"]

PATTERNS = [
    # A/c XX8899 debited INR 500.00 Dt 22-10-26 thru UPI:429833335555. Bal INR 2,000.00
    P(
        r"A/c\s*X*(?P<acct>\d{4})\s+(?P<dir>debited|credited)\s+INR\s*(?P<amount>[\d,]+(?:\.\d+)?)"
        r"\s+Dt\s+(?P<date>[\d-]+)\s+thru\s+UPI:(?P<ref>\d+)\.?\s+Bal\s+INR\s*"
        r"(?P<bal>[\d,]+(?:\.\d+)?)"
    ),
]


def parse(body: str) -> ParsedTxn | None:
    return match_first(body, PATTERNS, BANK)
