"""Canara Bank. Senders: AX-CANBNK, VM-CANBNK."""

from hisaab.parsers.banks._base import P, match_first
from hisaab.parsers.types import ParsedTxn

BANK = "Canara Bank"
SENDERS = ["CANBNK"]

PATTERNS = [
    # An amount of INR 350.00 has been DEBITED to your account XXX1122 on 24/10/2026 towards
    # UPI/429855559999/Swiggy. Total Avail.bal INR 1,200.00. - Canara Bank
    P(
        r"amount of INR\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+has been (?P<dir>DEBITED|CREDITED)\s+to "
        r"your account\s*X*(?P<acct>\d{4})\s+on\s+(?P<date>[\d/-]+)\s+towards\s+UPI/(?P<ref>\d+)/"
        r"(?P<name>[^.]+?)\.\s*Total Avail\.bal INR\s*(?P<bal>[\d,]+(?:\.\d+)?)"
    ),
]


def parse(body: str) -> ParsedTxn | None:
    return match_first(body, PATTERNS, BANK)
