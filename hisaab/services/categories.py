"""Categories and user rules ("apply to all from this merchant")."""

from __future__ import annotations

from sqlmodel import Session, select

from hisaab.core import models as m
from hisaab.parsers.categorize import Categorizer, CategoryRule, LLMCategorizer


def category_names(session: Session) -> list[str]:
    return [c.name for c in session.exec(select(m.Category).order_by(m.Category.name)).all()]


def category_id(session: Session, name: str | None) -> int | None:
    """Id for a category name (case-insensitive); ``None`` when name is empty or unknown."""
    if not name:
        return None
    for c in session.exec(select(m.Category)).all():
        if c.name.lower() == name.lower():
            return c.id
    return None


def category_name(session: Session, cid: int | None) -> str | None:
    if cid is None:
        return None
    c = session.get(m.Category, cid)
    return c.name if c else None


def add_category(session: Session, name: str, icon: str = "") -> m.Category:
    name = name.strip()
    if not name:
        raise ValueError("category name is empty")
    existing = category_id(session, name)
    if existing:
        return session.get(m.Category, existing)
    cat = m.Category(name=name, icon=icon)
    session.add(cat)
    session.commit()
    return cat


def load_rules(session: Session) -> list[CategoryRule]:
    out = []
    for r in session.exec(select(m.Rule).order_by(m.Rule.id.desc())).all():
        name = category_name(session, r.category_id)
        if name:
            out.append(CategoryRule(r.match_field, r.pattern, name))
    return out


def build_categorizer(session: Session, llm: LLMCategorizer | None = None) -> Categorizer:
    """Categorizer with the user's rules (newest first) and the category list for the LLM."""
    return Categorizer(rules=load_rules(session), llm=llm, categories=category_names(session))


def rule_target(txn: m.Txn) -> tuple[str, str] | None:
    """Which field a rule built from this transaction should match on."""
    for field in ("merchant", "counterparty_vpa", "counterparty_name"):
        value = getattr(txn, field)
        if value:
            return field, value
    return None


def set_txn_category(
    session: Session, txn_id: int, category: str, apply_to_all: bool = False
) -> int:
    """Set a transaction's category; with ``apply_to_all`` create a rule and recategorize
    every matching transaction. Returns how many transactions changed."""
    txn = session.get(m.Txn, txn_id)
    if txn is None:
        raise LookupError(f"transaction {txn_id} not found")
    cid = category_id(session, category)
    if cid is None:
        cid = add_category(session, category).id
    changed = [txn]
    if apply_to_all:
        target = rule_target(txn)
        if target is None:
            raise ValueError("transaction has no merchant, UPI ID or name to build a rule from")
        field, value = target
        session.add(
            m.Rule(match_field=field, pattern=value, category_id=cid, created_from_txn=txn.id)
        )
        rule = CategoryRule(field, value, category)
        for other in session.exec(select(m.Txn)).all():
            if other.id != txn.id and rule.matches(other):  # type: ignore[arg-type]
                changed.append(other)
    for t in changed:
        t.category_id = cid
        t.confidence = max(t.confidence, 1.0 if t is txn else 0.9)
        session.add(t)
    session.commit()
    return len(changed)


def delete_rule(session: Session, rule_id: int) -> None:
    rule = session.get(m.Rule, rule_id)
    if rule is not None:
        session.delete(rule)
        session.commit()
