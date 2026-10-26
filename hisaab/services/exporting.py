"""CSV and JSON export. Raw SMS text is never exported."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path

from sqlmodel import Session, select

from hisaab.core import models as m
from hisaab.services.insights import txn_frame

TABLES = [m.Category, m.Rule, m.Txn, m.Group, m.Member, m.Expense, m.ExpenseShare, m.Settlement]


def export_transactions_csv(session: Session, path: str | Path) -> Path:
    """Transactions as CSV (no raw SMS text)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = txn_frame(session).drop(columns=["amount_paise"])
    df.to_csv(path, index=False)
    return path


def _plain(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def export_json(session: Session, path: str | Path) -> Path:
    """Every table except raw message bodies, as one JSON document."""
    data: dict[str, list[dict]] = {}
    for table in TABLES:
        rows = session.exec(select(table)).all()
        data[table.__tablename__] = [
            {k: _plain(v) for k, v in row.model_dump().items()} for row in rows
        ]
    raw = session.exec(select(m.RawMessage)).all()
    data["raw_message"] = [
        {
            "id": r.id,
            "source": r.source.value,
            "sender": r.sender,
            "status": r.status.value,
            "received_at": _plain(r.received_at),
        }
        for r in raw
    ]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
