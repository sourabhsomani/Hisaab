"""Kotak Mahindra Bank. Senders: AX-KOTAKB, VM-KOTAKB."""

from hisaab.core.models import Direction
from hisaab.parsers.banks._base import P, match_first
from hisaab.parsers.types import ParsedTxn

BANK = "Kotak Bank"
SENDERS = ["KOTAKB", "KMBANK"]
D, C = Direction.DEBIT, Direction.CREDIT

PATTERNS = [
    # Sent Rs.300.00 from Kotak Bank AC X4567 to amit@ybl on 23-10-26.UPI Ref 429822223333.
    P(
        r"Sent\s+Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+from Kotak Bank AC\s*X*(?P<acct>\d{4})\s+"
        r"to\s+(?P<name>\S+?)\s+on\s+(?P<date>[\d-]+)\.\s*UPI Ref:?\s*(?P<ref>\d+)",
        D,
    ),
    # Received Rs.300.00 in your Kotak Bank AC X4567 from priya@okhdfcbank on 23-10-26.UPI Ref:..
    P(
        r"Received\s+Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+in your Kotak Bank AC\s*X*"
        r"(?P<acct>\d{4})\s+from\s+(?P<name>\S+?)\s+on\s+(?P<date>[\d-]+)\.\s*UPI Ref:?\s*"
        r"(?P<ref>\d+)",
        C,
    ),
]


def parse(body: str) -> ParsedTxn | None:
    return match_first(body, PATTERNS, BANK)
