"""HDFC Bank. Senders: AX-HDFCBK, VM-HDFCBK, JD-HDFCBK."""

from hisaab.core.models import Direction
from hisaab.parsers.banks._base import P, match_first
from hisaab.parsers.types import ParsedTxn

BANK = "HDFC Bank"
SENDERS = ["HDFCBK", "HDFCBN"]
D, C = Direction.DEBIT, Direction.CREDIT

PATTERNS = [
    # Sent Rs.450.00 From HDFC Bank A/C *1234 To RAHUL KUMAR On 24/10/26 Ref 429812345678
    P(
        r"Sent\s+Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+from\s+HDFC Bank A/c\s*[*x]*(?P<acct>\d{4})"
        r"\s+to\s+(?P<name>.+?)\s+on\s+(?P<date>[\d/-]+)\.?\s+Ref\s*(?P<ref>\d+)",
        D,
    ),
    # Rs.450.00 debited from a/c **1234 on 24-10-26 to VPA rahul@okaxis(UPI Ref No 429812345678)
    P(
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+debited from a/c\s*[*x]*(?P<acct>\d{4})\s+on\s+"
        r"(?P<date>[\d/-]+)\s+to\s+VPA\s+(?P<vpa>\S+?)\s*\(UPI Ref No\.?\s*(?P<ref>\d+)\)",
        D,
    ),
    # Rs.450.00 credited to HDFC Bank A/c XX1234 on 25-10-26 from VPA rahul@okaxis (UPI 4299..)
    P(
        r"Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+credited to HDFC Bank A/c\s*[*x]*(?P<acct>\d{4})"
        r"\s+on\s+(?P<date>[\d/-]+)\s+from\s+VPA\s+(?P<vpa>\S+?)\s*\(UPI\s*(?P<ref>\d+)\)",
        C,
    ),
    # Spent Rs.250.00 On HDFC Bank Card 9876 At RAZ*SWIGGY On 2026-10-20:13:45:11 Bal Rs.12345.67
    P(
        r"Spent\s+Rs\.?\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+On HDFC Bank Card\s*[*x]*(?P<acct>\d{4})"
        r"\s+At\s+(?P<merchant>.+?)\s+On\s+(?P<date>[\d:-]+)",
        D,
    ),
]


def parse(body: str) -> ParsedTxn | None:
    return match_first(body, PATTERNS, BANK)
