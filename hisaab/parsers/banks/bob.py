"""Bank of Baroda. Senders: AX-BOBTXN, VM-BOBSMS."""

from hisaab.core.models import Direction
from hisaab.parsers.banks._base import P, match_first
from hisaab.parsers.types import ParsedTxn

BANK = "Bank of Baroda"
SENDERS = ["BOBTXN", "BOBSMS", "BARODA"]
D, C = Direction.DEBIT, Direction.CREDIT

PATTERNS = [
    # Rs.700.00 transferred from A/c ...6655 to:UPI/429844447777. Total Bal:Rs.3,000.00CR.
    # Avlbl Amt:Rs.3,000.00(25-10-2026 14:02:11)
    P(
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+transferred from A/c\s*\.*(?P<acct>\d{4})\s+"
        r"to:UPI/(?P<ref>\d+)\..*?Avlbl Amt:Rs\.?(?P<bal>[\d,]+(?:\.\d+)?)\((?P<date>[^)]+)\)",
        D,
    ),
    # Rs.700.00 Credited to A/c ...6655 thru UPI/429844448888 by rahul@okaxis. Total Bal:...
    P(
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+Credited to A/c\s*\.*(?P<acct>\d{4})\s+thru\s+"
        r"UPI/(?P<ref>\d+)\s+by\s+(?P<name>\S+?)\..*?Avlbl Amt:Rs\.?(?P<bal>[\d,]+(?:\.\d+)?)"
        r"\((?P<date>[^)]+)\)",
        C,
    ),
]


def parse(body: str) -> ParsedTxn | None:
    return match_first(body, PATTERNS, BANK)
