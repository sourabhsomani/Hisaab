"""Axis Bank. Senders: AX-AXISBK, VM-AXISBK."""

from hisaab.parsers.banks._base import P, match_first
from hisaab.parsers.types import ParsedTxn

BANK = "Axis Bank"
SENDERS = ["AXISBK"]

PATTERNS = [
    # INR 600.00 debited A/c no. XX7788 23-10-26 19:02:11 UPI/P2A/429811112222/PRIYA SHARMA
    P(
        r"INR\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+(?P<dir>debited|credited)\s+A/c no\.\s*X*"
        r"(?P<acct>\d{4})\s+(?P<date>[\d-]+\s+[\d:]+)\s+UPI/P2[AM]/(?P<ref>\d+)/(?P<name>[^/\n]+?)"
        r"(?=\s+Not you|\s+Axis|\s*$)"
    ),
    # Debit INR 600.00 A/c no. XX7788 23-10-26 19:02:11 UPI/P2M/429811114444/BLINKIT
    P(
        r"(?P<dir>Debit|Credit)\s+INR\s*(?P<amount>[\d,]+(?:\.\d+)?)\s+A/c no\.\s*X*"
        r"(?P<acct>\d{4})\s+(?P<date>[\d-]+\s+[\d:]+)\s+UPI/P2[AM]/(?P<ref>\d+)/(?P<name>[^/\n]+?)"
        r"(?=\s+Not you|\s+Axis|\s*$)"
    ),
]


def parse(body: str) -> ParsedTxn | None:
    return match_first(body, PATTERNS, BANK)
