"""State Bank of India. Senders: JD-SBIUPI, AX-SBIINB, VM-SBIPSG."""

from hisaab.core.models import Direction
from hisaab.parsers.banks._base import P, match_first
from hisaab.parsers.types import ParsedTxn

BANK = "SBI"
SENDERS = ["SBIUPI", "SBIINB", "SBIPSG", "CBSSBI", "ATMSBI"]
D, C = Direction.DEBIT, Direction.CREDIT

PATTERNS = [
    # Dear UPI user A/C X5678 debited by 450.0 on date 24Oct26 trf to RAHUL KUMAR Refno 4298...
    P(
        r"A/C\s*X*(?P<acct>\d{4})\s+(?P<dir>debited|credited)\s+by\s+(?:Rs\.?\s*)?"
        r"(?P<amount>[\d,]+(?:\.\d+)?)\s+on\s+date\s+(?P<date>\w+)\s+trf\s+(?:to|from)\s+"
        r"(?P<name>.+?)\s+Refno\s+(?P<ref>\d+)"
    ),
    # Dear SBI UPI User, ur A/cX5678 credited by Rs450 on 25Oct26 by (Ref no 429987654321)
    P(
        r"ur A/c\s*X*(?P<acct>\d{4})\s+(?P<dir>credited|debited)\s+by\s+Rs\.?\s*"
        r"(?P<amount>[\d,]+(?:\.\d+)?)\s+on\s+(?P<date>\w+)\s+by\s+\(Ref no\s*(?P<ref>\d+)\)"
    ),
    # Your A/C XXXXX5678 Credited INR 1,000.00 on 25/10/26 -Deposit by transfer from PRIYA SHARMA.
    P(
        r"Your A/C\s*X*(?P<acct>\d{4})\s+(?P<dir>Credited|Debited)\s+INR\s*"
        r"(?P<amount>[\d,]+(?:\.\d+)?)\s+on\s+(?P<date>[\d/-]+)\s+-.*?(?:from|to)\s+"
        r"(?P<name>[A-Za-z .]+?)\.\s"
    ),
]


def parse(body: str) -> ParsedTxn | None:
    return match_first(body, PATTERNS, BANK)
