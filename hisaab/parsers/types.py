"""Shared parser types."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from hisaab.core.enums import StrEnum
from hisaab.core.models import Direction


@dataclass
class ParsedTxn:
    """Fields extracted from one bank or UPI SMS."""

    direction: Direction
    amount_paise: int
    account_tail: str | None = None
    counterparty_name: str | None = None
    counterparty_vpa: str | None = None
    upi_ref: str | None = None
    txn_at: datetime | None = None
    balance_paise: int | None = None
    merchant: str | None = None
    bank: str | None = None
    confidence: float = 0.0

    def copy(self, **changes) -> ParsedTxn:
        return replace(self, **changes)

    def as_dict(self) -> dict:
        """JSON-friendly dict used by fixture tests and the accuracy report."""
        return {
            "direction": self.direction.value,
            "amount_paise": self.amount_paise,
            "account_tail": self.account_tail,
            "counterparty_name": self.counterparty_name,
            "counterparty_vpa": self.counterparty_vpa,
            "upi_ref": self.upi_ref,
            "txn_at": self.txn_at.isoformat() if self.txn_at else None,
        }


class ResultStatus(StrEnum):
    PARSED = "parsed"
    REVIEW = "review"
    IGNORED = "ignored"
    DUPLICATE = "duplicate"


@dataclass
class ParseResult:
    """Outcome of running one message through the pipeline."""

    status: ResultStatus
    sender: str
    body: str
    received_at: datetime | None = None
    txn: ParsedTxn | None = None
    category: str | None = None
    confidence: float = 0.0
    reason: str = ""
    notes: list[str] = field(default_factory=list)
