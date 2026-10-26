"""ICICI Bank. Senders: AX-ICICIB, VM-ICICIT."""

from hisaab.core.models import Direction
from hisaab.parsers.banks._base import P, match_first
from hisaab.parsers.types import ParsedTxn

BANK = "ICICI Bank"
SENDERS = ["ICICIB", "ICICIT"]
D, C = Direction.DEBIT, Direction.CREDIT

PATTERNS = [
    # ICICI Bank Acct XX321 debited for Rs 1200.00 on 21-Oct-26; ZOMATO credited. UPI:5298...
    P(
        r"ICICI Bank Acct\s*X*(?P<acct>\d{3,4})\s+debited for Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)"
        r"\s+on\s+(?P<date>[\w-]+);\s*(?P<name>.+?)\s+credited\.\s*UPI:(?P<ref>\d+)",
        D,
    ),
    # Acct XX321 is credited with Rs 450.00 on 25-Oct-26 from RAHUL KUMAR. UPI:529987654321
    P(
        r"Acct\s*X*(?P<acct>\d{3,4})\s+is credited with Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"on\s+(?P<date>[\w-]+)\s+from\s+(?P<name>.+?)\.\s*UPI:(?P<ref>\d+)",
        C,
    ),
    # INR 999.00 spent using ICICI Bank Card XX4455 on 22-Oct-26 on AMAZON. Avl Limit: INR 45,000
    P(
        r"INR\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+spent using ICICI Bank Card\s*X*(?P<acct>\d{4})\s+"
        r"on\s+(?P<date>[\w-]+)\s+on\s+(?P<merchant>.+?)\.",
        D,
    ),
]


def parse(body: str) -> ParsedTxn | None:
    return match_first(body, PATTERNS, BANK)
