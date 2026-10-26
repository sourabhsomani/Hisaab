"""SQLModel tables. Amounts are integer paise; balances are always computed, never stored."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel

from hisaab.core.enums import StrEnum


def now() -> datetime:
    """Naive local wall-clock time. Bank SMS carry local (IST) times, so we store naive values."""
    return datetime.now().replace(microsecond=0)


def DateField(**kwargs: Any) -> Any:  # noqa: N802 - reads like a type in model definitions
    """A naive ``DATETIME`` column, independent of SQLModel's timezone defaults."""
    return Field(sa_type=DateTime(timezone=False), **kwargs)


class Source(StrEnum):
    PASTE = "paste"
    XML = "xml"
    CSV = "csv"
    WHATSAPP = "whatsapp"
    MANUAL = "manual"


class MessageStatus(StrEnum):
    PARSED = "parsed"
    REVIEW = "review"
    IGNORED = "ignored"
    DUPLICATE = "duplicate"


class Direction(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class GroupKind(StrEnum):
    TRIP = "trip"
    FLAT = "flat"
    COUPLE = "couple"
    OTHER = "other"


class SplitType(StrEnum):
    EQUAL = "equal"
    EXACT = "exact"
    PERCENTAGE = "percentage"
    SHARES = "shares"
    ADJUSTMENT = "adjustment"


class SettlementMethod(StrEnum):
    UPI_SMS = "upi_sms"
    MANUAL = "manual"


class SettlementStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class RawMessage(SQLModel, table=True):
    __tablename__ = "raw_message"

    id: int | None = Field(default=None, primary_key=True)
    source: Source = Source.PASTE
    sender: str = ""
    body: str | None = None
    received_at: datetime | None = DateField(default=None)
    hash: str = Field(index=True, unique=True)
    status: MessageStatus = MessageStatus.REVIEW


class Txn(SQLModel, table=True):
    __tablename__ = "transaction"

    id: int | None = Field(default=None, primary_key=True)
    raw_message_id: int | None = Field(default=None, foreign_key="raw_message.id")
    direction: Direction
    amount_paise: int
    account_tail: str | None = None
    merchant: str | None = None
    counterparty_name: str | None = None
    counterparty_vpa: str | None = None
    upi_ref: str | None = Field(default=None, index=True)
    txn_at: datetime | None = DateField(default=None)
    category_id: int | None = Field(default=None, foreign_key="category.id")
    confidence: float = 0.0
    is_split: bool = False


class Category(SQLModel, table=True):
    __tablename__ = "category"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    icon: str = ""
    parent_id: int | None = Field(default=None, foreign_key="category.id")


class Rule(SQLModel, table=True):
    __tablename__ = "rule"

    id: int | None = Field(default=None, primary_key=True)
    match_field: str = "merchant"
    pattern: str
    category_id: int = Field(foreign_key="category.id")
    created_from_txn: int | None = Field(default=None, foreign_key="transaction.id")


class Group(SQLModel, table=True):
    __tablename__ = "group"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    kind: GroupKind = GroupKind.OTHER
    created_at: datetime = DateField(default_factory=now)
    archived: bool = False


class Member(SQLModel, table=True):
    __tablename__ = "member"

    id: int | None = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id", index=True)
    name: str
    upi_vpa: str | None = None
    phone: str | None = None
    is_me: bool = False
    aliases: str = ""  # comma-separated names as banks print them, e.g. "RAHUL KUM"

    def alias_list(self) -> list[str]:
        return [a.strip() for a in self.aliases.split(",") if a.strip()]


class Expense(SQLModel, table=True):
    __tablename__ = "expense"

    id: int | None = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id", index=True)
    transaction_id: int | None = Field(default=None, foreign_key="transaction.id")
    description: str
    total_paise: int
    paid_by_member_id: int = Field(foreign_key="member.id")
    split_type: SplitType = SplitType.EQUAL
    spent_at: datetime = DateField(default_factory=now)


class ExpenseShare(SQLModel, table=True):
    __tablename__ = "expense_share"

    expense_id: int = Field(foreign_key="expense.id", primary_key=True)
    member_id: int = Field(foreign_key="member.id", primary_key=True)
    share_paise: int
    share_value: float | None = None


class Settlement(SQLModel, table=True):
    __tablename__ = "settlement"

    id: int | None = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id", index=True)
    from_member_id: int = Field(foreign_key="member.id")
    to_member_id: int = Field(foreign_key="member.id")
    amount_paise: int
    transaction_id: int | None = Field(default=None, foreign_key="transaction.id")
    method: SettlementMethod = SettlementMethod.MANUAL
    status: SettlementStatus = SettlementStatus.CONFIRMED
    settled_at: datetime = DateField(default_factory=now)
