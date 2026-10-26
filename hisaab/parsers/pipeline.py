"""The five-stage SMS pipeline: filter → extract → normalize → dedup → categorize."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import ModuleType

from hisaab.parsers import generic
from hisaab.parsers.categorize import REVIEW_THRESHOLD, Categorizer
from hisaab.parsers.dedup import is_same_payment, merge
from hisaab.parsers.filter import classify_message
from hisaab.parsers.normalize import normalize_txn
from hisaab.parsers.types import ParsedTxn, ParseResult, ResultStatus

LLMExtractor = Callable[[str], ParsedTxn | None]


@dataclass(frozen=True)
class Message:
    sender: str
    body: str
    received_at: datetime | None = None


def _sender_matches(sender: str, senders: Sequence[str]) -> bool:
    s = (sender or "").upper()
    return any(tag in s for tag in senders)


@dataclass
class Pipeline:
    banks: Sequence[ModuleType] = field(default_factory=list)
    categorizer: Categorizer = field(default_factory=Categorizer)
    llm_extract: LLMExtractor | None = None
    threshold: float = REVIEW_THRESHOLD

    def extract(self, sender: str, body: str) -> ParsedTxn | None:
        """Bank plugins whose SENDERS match first, then every plugin, then generic, then LLM."""
        matching = [b for b in self.banks if _sender_matches(sender, b.SENDERS)]
        others = [b for b in self.banks if b not in matching]
        for bank in [*matching, *others]:
            txn = bank.parse(body)
            if txn is not None:
                return txn
        txn = generic.parse(body)
        if txn is None and self.llm_extract is not None:
            try:
                txn = self.llm_extract(body)
            except Exception:
                txn = None
        return txn

    def process(self, sender: str, body: str, received_at: datetime | None = None) -> ParseResult:
        """Run one message through filter, extract, normalize and categorize."""
        keep, reason = classify_message(sender, body)
        if not keep:
            return ParseResult(ResultStatus.IGNORED, sender, body, received_at, reason=reason)
        txn = self.extract(sender, body)
        if txn is None:
            return ParseResult(ResultStatus.REVIEW, sender, body, received_at, reason="unparsed")
        if txn.txn_at is None and received_at is not None:
            txn = txn.copy(txn_at=received_at)
        txn = normalize_txn(txn)
        category, cat_conf = self.categorizer.categorize(txn)
        confidence = round(min(txn.confidence, cat_conf), 2)
        status = ResultStatus.PARSED if confidence >= self.threshold else ResultStatus.REVIEW
        reason = "ok" if status is ResultStatus.PARSED else "low_confidence"
        return ParseResult(status, sender, body, received_at, txn, category, confidence, reason)

    def process_many(self, messages: Iterable[Message]) -> list[ParseResult]:
        """Process a batch; the second SMS for the same payment is marked duplicate."""
        results: list[ParseResult] = []
        seen: list[ParseResult] = []
        for msg in messages:
            res = self.process(msg.sender, msg.body, msg.received_at)
            if res.txn is not None:
                for prev in seen:
                    if prev.txn is not None and is_same_payment(prev.txn, res.txn):
                        prev.txn = merge(prev.txn, res.txn)
                        res.status = ResultStatus.DUPLICATE
                        res.reason = "duplicate_payment"
                        break
                else:
                    seen.append(res)
            results.append(res)
        return results


def summarize(results: Iterable[ParseResult]) -> dict[str, int]:
    """Count results by status, for the Import tab."""
    counts = {s.value: 0 for s in ResultStatus}
    for r in results:
        counts[r.status.value] += 1
    return counts
