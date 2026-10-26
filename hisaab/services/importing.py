"""Import SMS and statements into the database, with dedup against what is already stored."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta

from sqlmodel import Session, select

from hisaab.core import models as m
from hisaab.parsers.categorize import REVIEW_THRESHOLD
from hisaab.parsers.dedup import is_same_payment, message_hash
from hisaab.parsers.pipeline import Message, Pipeline, default_pipeline
from hisaab.parsers.types import ParsedTxn, ResultStatus
from hisaab.services.categories import build_categorizer, category_id

_STATUS = {
    ResultStatus.PARSED: m.MessageStatus.PARSED,
    ResultStatus.REVIEW: m.MessageStatus.REVIEW,
    ResultStatus.IGNORED: m.MessageStatus.IGNORED,
    ResultStatus.DUPLICATE: m.MessageStatus.DUPLICATE,
}


@dataclass
class ImportReport:
    total: int = 0
    parsed: int = 0
    review: int = 0
    ignored: int = 0
    duplicate: int = 0
    already_imported: int = 0
    txn_ids: list[int] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.total} messages: {self.parsed} transactions, {self.review} to review, "
            f"{self.duplicate} duplicates merged, {self.ignored} ignored"
            + (f", {self.already_imported} already imported" if self.already_imported else "")
        )


def to_parsed(txn: m.Txn) -> ParsedTxn:
    return ParsedTxn(
        direction=txn.direction,
        amount_paise=txn.amount_paise,
        account_tail=txn.account_tail,
        counterparty_name=txn.counterparty_name,
        counterparty_vpa=txn.counterparty_vpa,
        upi_ref=txn.upi_ref,
        txn_at=txn.txn_at,
        merchant=txn.merchant,
        confidence=txn.confidence,
    )


def find_existing(session: Session, parsed: ParsedTxn) -> m.Txn | None:
    """A stored transaction that is the same payment (by UPI ref or amount+tail+time)."""
    if parsed.upi_ref:
        hit = session.exec(select(m.Txn).where(m.Txn.upi_ref == parsed.upi_ref)).first()
        if hit:
            return hit
    q = select(m.Txn).where(
        m.Txn.amount_paise == parsed.amount_paise, m.Txn.direction == parsed.direction
    )
    if parsed.txn_at is not None:
        day = parsed.txn_at.replace(hour=0, minute=0, second=0)
        q = q.where(m.Txn.txn_at >= day - timedelta(days=1), m.Txn.txn_at < day + timedelta(days=2))
    for cand in session.exec(q).all():
        if is_same_payment(to_parsed(cand), parsed):
            return cand
    return None


def store_txn(
    session: Session,
    parsed: ParsedTxn,
    category: str | None,
    confidence: float,
    raw_id: int | None = None,
) -> m.Txn:
    txn = m.Txn(
        raw_message_id=raw_id,
        direction=parsed.direction,
        amount_paise=parsed.amount_paise,
        account_tail=parsed.account_tail,
        merchant=parsed.merchant,
        counterparty_name=parsed.counterparty_name,
        counterparty_vpa=parsed.counterparty_vpa,
        upi_ref=parsed.upi_ref,
        txn_at=parsed.txn_at,
        category_id=category_id(session, category),
        confidence=confidence,
    )
    session.add(txn)
    session.flush()
    return txn


def import_messages(
    session: Session,
    messages: Iterable[Message],
    source: m.Source = m.Source.PASTE,
    pipeline: Pipeline | None = None,
    keep_raw: bool = True,
) -> ImportReport:
    """Run messages through the pipeline and store raw messages plus transactions.

    Re-importing the same SMS is a no-op (hash), and the bank + UPI-app pair for one payment
    becomes a single transaction, both within the batch and against earlier imports.
    """
    pipe = pipeline or default_pipeline(categorizer=build_categorizer(session))
    report = ImportReport()
    fresh: list[Message] = []
    hashes: set[str] = set()
    for msg in messages:
        report.total += 1
        h = message_hash(msg.sender, msg.body)
        exists = session.exec(select(m.RawMessage.id).where(m.RawMessage.hash == h)).first()
        if exists or h in hashes:
            report.already_imported += 1
            continue
        hashes.add(h)
        fresh.append(msg)

    for msg, res in zip(fresh, pipe.process_many(fresh), strict=True):
        status = res.status
        existing = None
        if res.txn is not None and status is not ResultStatus.DUPLICATE:
            existing = find_existing(session, res.txn)
            if existing is not None:
                status = ResultStatus.DUPLICATE
        raw = m.RawMessage(
            source=source,
            sender=msg.sender,
            body=msg.body if keep_raw else None,
            received_at=msg.received_at,
            hash=message_hash(msg.sender, msg.body),
            status=_STATUS[status],
        )
        session.add(raw)
        session.flush()
        setattr(report, status.value, getattr(report, status.value) + 1)
        if res.txn is not None and status in (ResultStatus.PARSED, ResultStatus.REVIEW):
            txn = store_txn(session, res.txn, res.category, res.confidence, raw.id)
            report.txn_ids.append(txn.id)
    session.commit()
    return report


def import_parsed(
    session: Session,
    txns: Iterable[ParsedTxn],
    source: m.Source = m.Source.CSV,
    pipeline: Pipeline | None = None,
) -> ImportReport:
    """Store already-parsed transactions (bank statements), skipping known payments."""
    cat = (pipeline.categorizer if pipeline else None) or build_categorizer(session)
    report = ImportReport()
    for parsed in txns:
        report.total += 1
        if find_existing(session, parsed) is not None:
            report.duplicate += 1
            continue
        category, cat_conf = cat.categorize(parsed)
        conf = round(min(parsed.confidence, cat_conf), 2)
        txn = store_txn(session, parsed, category, conf)
        report.txn_ids.append(txn.id)
        if conf >= REVIEW_THRESHOLD:
            report.parsed += 1
        else:
            report.review += 1
    session.commit()
    return report


def review_inbox(session: Session, threshold: float = REVIEW_THRESHOLD) -> list[m.Txn]:
    """Transactions waiting for a quick fix: low confidence or no category."""
    q = select(m.Txn).where((m.Txn.confidence < threshold) | (m.Txn.category_id.is_(None)))
    return list(session.exec(q.order_by(m.Txn.txn_at.desc())).all())


def unparsed_messages(session: Session) -> list[m.RawMessage]:
    """Kept SMS the parser could not read at all."""
    q = (
        select(m.RawMessage)
        .where(m.RawMessage.status == m.MessageStatus.REVIEW)
        .where(
            ~m.RawMessage.id.in_(
                select(m.Txn.raw_message_id).where(m.Txn.raw_message_id.is_not(None))
            )
        )
    )
    return list(session.exec(q).all())


def confirm_txn(session: Session, txn_id: int) -> m.Txn:
    """Mark a reviewed transaction as correct."""
    txn = session.get(m.Txn, txn_id)
    if txn is None:
        raise LookupError(f"transaction {txn_id} not found")
    txn.confidence = 1.0
    session.add(txn)
    session.commit()
    return txn


def add_manual_txn(session: Session, parsed: ParsedTxn, category: str | None = None) -> m.Txn:
    """Store a transaction the user fixed or typed by hand."""
    txn = store_txn(session, parsed, category, 1.0)
    session.commit()
    return txn


def purge_raw_bodies(session: Session) -> int:
    """Privacy setting: drop raw SMS text after parsing. Returns rows cleared."""
    rows = session.exec(select(m.RawMessage).where(m.RawMessage.body.is_not(None))).all()
    for r in rows:
        r.body = None
        session.add(r)
    session.commit()
    return len(rows)
