"""Personal dashboard numbers: monthly spend, categories, merchants and budgets."""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlmodel import Session, select

from hisaab.core import models as m

COLUMNS = [
    "id",
    "date",
    "month",
    "direction",
    "amount_paise",
    "amount",
    "merchant",
    "counterparty",
    "category",
    "is_split",
]
TRANSFERS = "Transfers"


def current_month(today: date | None = None) -> str:
    return (today or date.today()).strftime("%Y-%m")


def txn_frame(session: Session) -> pd.DataFrame:
    """All transactions as a DataFrame; ``amount`` is in rupees for charts."""
    cats = {c.id: c.name for c in session.exec(select(m.Category)).all()}
    rows = []
    for t in session.exec(select(m.Txn)).all():
        when = t.txn_at
        rows.append(
            {
                "id": t.id,
                "date": when,
                "month": when.strftime("%Y-%m") if when else None,
                "direction": t.direction.value,
                "amount_paise": t.amount_paise,
                "amount": t.amount_paise / 100,
                "merchant": t.merchant,
                "counterparty": t.counterparty_name or t.counterparty_vpa,
                "category": cats.get(t.category_id, "Uncategorized"),
                "is_split": t.is_split,
            }
        )
    return pd.DataFrame(rows, columns=COLUMNS)


def _debits(df: pd.DataFrame, month: str | None, exclude_transfers: bool) -> pd.DataFrame:
    out = df[df["direction"] == "debit"]
    if month:
        out = out[out["month"] == month]
    if exclude_transfers:
        out = out[out["category"] != TRANSFERS]
    return out


def monthly_spend(session: Session) -> pd.DataFrame:
    """Spent and received per month (rupees), oldest first."""
    df = txn_frame(session).dropna(subset=["month"])
    if df.empty:
        return pd.DataFrame(columns=["month", "spent", "received"])
    pivot = df.pivot_table(
        index="month", columns="direction", values="amount", aggfunc="sum", fill_value=0
    )
    out = pd.DataFrame(
        {
            "month": pivot.index,
            "spent": pivot.get("debit", pd.Series(0, index=pivot.index)).values,
            "received": pivot.get("credit", pd.Series(0, index=pivot.index)).values,
        }
    )
    return out.sort_values("month").reset_index(drop=True)


def spend_by_category(
    session: Session, month: str | None = None, exclude_transfers: bool = False
) -> pd.DataFrame:
    df = _debits(txn_frame(session), month, exclude_transfers)
    if df.empty:
        return pd.DataFrame(columns=["category", "amount"])
    out = df.groupby("category", as_index=False)["amount"].sum()
    return out.sort_values(["amount", "category"], ascending=[False, True]).reset_index(drop=True)


def top_merchants(session: Session, month: str | None = None, limit: int = 10) -> pd.DataFrame:
    df = _debits(txn_frame(session), month, exclude_transfers=True).dropna(subset=["merchant"])
    if df.empty:
        return pd.DataFrame(columns=["merchant", "amount", "count"])
    out = df.groupby("merchant").agg(amount=("amount", "sum"), count=("id", "count"))
    out = out.reset_index().sort_values(["amount", "merchant"], ascending=[False, True])
    return out.head(limit).reset_index(drop=True)


def budget_status(session: Session, budgets: dict[str, int], month: str) -> pd.DataFrame:
    """Budget vs spend per category for a month (rupees). ``used`` is a fraction."""
    spent = dict(spend_by_category(session, month).itertuples(index=False, name=None))
    rows = []
    for cat, paise in sorted(budgets.items()):
        budget = paise / 100
        used = spent.get(cat, 0.0)
        rows.append(
            {
                "category": cat,
                "budget": budget,
                "spent": used,
                "left": budget - used,
                "used": round(used / budget, 3) if budget else 0.0,
            }
        )
    return pd.DataFrame(rows, columns=["category", "budget", "spent", "left", "used"])
