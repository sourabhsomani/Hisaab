"""Stage 5: user rules, then merchant keywords, then an optional LLM."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from hisaab.core.models import Direction
from hisaab.parsers.normalize import merchant_map
from hisaab.parsers.types import ParsedTxn

RULE_CONFIDENCE = 1.0
KEYWORD_CONFIDENCE = 0.9
PERSON_CONFIDENCE = 0.75
REVIEW_THRESHOLD = 0.7

LLMCategorizer = Callable[[ParsedTxn, list[str]], tuple[str | None, float]]


@dataclass(frozen=True)
class CategoryRule:
    """``match_field`` is one of merchant, counterparty_name, counterparty_vpa."""

    match_field: str
    pattern: str
    category: str

    def matches(self, txn: ParsedTxn) -> bool:
        value = getattr(txn, self.match_field, None)
        if not value:
            return False
        return bool(re.search(re.escape(self.pattern), value, re.IGNORECASE))


_PERSON = re.compile(r"^[A-Za-z]{2,}(?:\s+[A-Za-z.]{1,}){0,3}$")


def looks_like_person(name: str | None) -> bool:
    """Heuristic: 1-4 alphabetic words, no digits or company words."""
    if not name or not _PERSON.match(name):
        return False
    return not re.search(r"(?i)\b(ltd|pvt|store|mart|services|bank|cafe|restaurant)\b", name)


@dataclass
class Categorizer:
    rules: list[CategoryRule] = field(default_factory=list)
    merchants: dict[str, dict] = field(default_factory=merchant_map)
    llm: LLMCategorizer | None = None
    categories: list[str] = field(default_factory=list)

    def by_rules(self, txn: ParsedTxn) -> str | None:
        for rule in self.rules:
            if rule.matches(txn):
                return rule.category
        return None

    def by_keywords(self, txn: ParsedTxn) -> str | None:
        if txn.merchant and txn.merchant in self.merchants:
            return self.merchants[txn.merchant].get("category")
        hay = " ".join(filter(None, [txn.merchant, txn.counterparty_name, txn.counterparty_vpa]))
        low = hay.lower()
        for info in self.merchants.values():
            if any(re.search(rf"\b{re.escape(k)}", low) for k in info.get("keywords", [])):
                return info.get("category")
        return None

    def categorize(self, txn: ParsedTxn) -> tuple[str | None, float]:
        """Return (category, confidence)."""
        cat = self.by_rules(txn)
        if cat:
            return cat, RULE_CONFIDENCE
        cat = self.by_keywords(txn)
        if cat:
            return cat, KEYWORD_CONFIDENCE
        if txn.direction is Direction.CREDIT or looks_like_person(txn.counterparty_name):
            return "Transfers", PERSON_CONFIDENCE
        if self.llm is not None:
            try:
                cat, conf = self.llm(txn, self.categories)
            except Exception:  # an optional local model must never break import
                cat, conf = None, 0.0
            if cat:
                return cat, conf
        return None, 0.0
