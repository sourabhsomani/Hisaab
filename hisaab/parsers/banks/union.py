"""Union Bank of India. Senders: AX-UNIONB, VM-UBOIIN."""

from hisaab.parsers.banks._base import P, match_first
from hisaab.parsers.types import ParsedTxn

BANK = "Union Bank of India"
SENDERS = ["UNIONB", "UBOIIN", "UBOI"]

PATTERNS = [
    # A/c *3344 Debited for Rs:120.00 on 23-10-2026 19:20:11 by Mob Bk ref no 429866661111
    # Avl Bal Rs:880.00
    P(
        r"A/c\s*\*(?P<acct>\d{4})\s+(?P<dir>Debited|Credited)\s+for\s+Rs:?\s*"
        r"(?P<amount>[\d,]+(?:\.\d+)?)\s+on\s+(?P<date>[\d-]+\s+[\d:]+)\s+by\s+.*?ref no\s*"
        r"(?P<ref>\d+)\s+Avl Bal Rs:?\s*(?P<bal>[\d,]+(?:\.\d+)?)"
    ),
]


def parse(body: str) -> ParsedTxn | None:
    return match_first(body, PATTERNS, BANK)
