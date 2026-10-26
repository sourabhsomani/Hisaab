"""Inbox tab: confirm drafts, fix categories, send a transaction to a group as a split."""

from __future__ import annotations

import gradio as gr
import pandas as pd
from sqlmodel import select

from hisaab.core import models as m
from hisaab.core.money import format_inr
from hisaab.services import groups as gsvc
from hisaab.services.categories import category_name, category_names, set_txn_category
from hisaab.services.importing import confirm_txn, review_inbox, unparsed_messages
from hisaab.ui.common import (
    Ctx,
    err,
    group_choices,
    member_choices,
    ok,
    parse_values,
    values_for,
)

COLUMNS = ["id", "date", "type", "amount", "to / from", "category", "confidence", "split"]


def _row(s, t: m.Txn) -> dict:
    who = t.merchant or t.counterparty_name or t.counterparty_vpa or ""
    return {
        "id": t.id,
        "date": t.txn_at.strftime("%d %b %Y") if t.txn_at else "",
        "type": "↑ paid" if t.direction is m.Direction.DEBIT else "↓ received",
        "amount": format_inr(t.amount_paise),
        "to / from": who,
        "category": category_name(s, t.category_id) or "—",
        "confidence": f"{t.confidence:.0%}",
        "split": "✓" if t.is_split else "",
    }


def inbox_table(ctx: Ctx, show_all: bool = False) -> pd.DataFrame:
    with ctx.session() as s:
        if show_all:
            txns = s.exec(select(m.Txn).order_by(m.Txn.txn_at.desc(), m.Txn.id.desc())).all()
        else:
            txns = review_inbox(s)
        return pd.DataFrame([_row(s, t) for t in txns], columns=COLUMNS)


def unparsed_text(ctx: Ctx) -> str:
    with ctx.session() as s:
        rows = unparsed_messages(s)
        if not rows:
            return ""
        lines = [
            f"**{len(rows)} SMS could not be read.** Add your bank (see CONTRIBUTING) or "
            "turn on the local LLM in Settings."
        ]
        lines += [
            f"- `{r.sender or 'pasted'}`: {(r.body or '(text deleted)')[:90]}…" for r in rows[:5]
        ]
        return "\n".join(lines)


def _txn_id(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("pick a transaction: type its id from the table") from None


def handle_category(ctx: Ctx, txn_id, category: str | None, apply_all: bool, show_all: bool):
    try:
        if not category:
            raise ValueError("pick a category")
        with ctx.session() as s:
            n = set_txn_category(s, _txn_id(txn_id), category, apply_to_all=apply_all)
        msg = ok(
            f"Saved as {category}"
            + (f" for {n} transactions, and future ones" if apply_all else ".")
        )
    except (ValueError, LookupError) as exc:
        msg = err(str(exc))
    return msg, inbox_table(ctx, show_all)


def handle_confirm(ctx: Ctx, txn_id, show_all: bool):
    try:
        with ctx.session() as s:
            confirm_txn(s, _txn_id(txn_id))
        msg = ok("Confirmed.")
    except (ValueError, LookupError) as exc:
        msg = err(str(exc))
    return msg, inbox_table(ctx, show_all)


def handle_split(
    ctx: Ctx, txn_id, group_id, participants, split_type: str, values_text: str, show_all: bool
):
    try:
        if not group_id:
            raise ValueError("pick a group")
        if not participants:
            raise ValueError("pick who shared this expense")
        names = dict((mid, label) for label, mid in member_choices(ctx, group_id))
        ids = [int(p) for p in participants]
        values = values_for(split_type, parse_values(values_text, ids, names))
        with ctx.session() as s:
            e = gsvc.expense_from_txn(s, _txn_id(txn_id), int(group_id), ids, split_type, values)
            group = gsvc.get_group(s, int(group_id))
            msg = ok(f"Split {format_inr(e.total_paise)} in {group.name}.")
    except (ValueError, LookupError) as exc:
        msg = err(str(exc))
    return msg, inbox_table(ctx, show_all)


def pick_row(df: pd.DataFrame, evt: gr.SelectData):
    """Clicking a table row puts its id in the id box."""
    row = evt.index[0] if isinstance(evt.index, list | tuple) else evt.index
    return int(df.iloc[row]["id"])


def build(ctx: Ctx) -> gr.Tab:
    with gr.Tab("Inbox") as tab:
        gr.Markdown(
            "### Review\nLow-confidence or uncategorized transactions wait here. "
            "Click a row to select it."
        )
        show_all = gr.Checkbox(label="Show all transactions", value=False)
        table = gr.Dataframe(value=inbox_table(ctx), headers=COLUMNS, interactive=False, wrap=True)
        unparsed = gr.Markdown(unparsed_text(ctx))
        txn_id = gr.Number(label="Transaction id", precision=0)
        with gr.Row():
            category = gr.Dropdown(choices=[], label="Category", allow_custom_value=True)
            apply_all = gr.Checkbox(label="Apply to all from this merchant")
        with gr.Row():
            save_btn = gr.Button("Save category", variant="primary")
            confirm_btn = gr.Button("Looks right ✓")
        with gr.Accordion("Split this transaction with a group", open=False):
            group = gr.Dropdown(choices=group_choices(ctx), label="Group")
            people = gr.Dropdown(choices=[], multiselect=True, label="Shared with")
            split_type = gr.Radio(
                ["equal", "exact", "percentage", "shares", "adjustment"],
                value="equal",
                label="Split",
            )
            values = gr.Textbox(
                label="Values (not for equal)", placeholder="Rahul=2, Priya=1   or   2, 1"
            )
            split_btn = gr.Button("Split")
        status = gr.Markdown()

        def refresh(all_):
            with ctx.session() as s:
                cats = category_names(s)
            return (
                inbox_table(ctx, all_),
                unparsed_text(ctx),
                gr.update(choices=cats),
                gr.update(choices=group_choices(ctx)),
            )

        outs = [table, unparsed, category, group]
        tab.select(refresh, show_all, outs)
        show_all.change(refresh, show_all, outs)
        table.select(pick_row, table, txn_id)
        group.change(
            lambda g: gr.update(
                choices=member_choices(ctx, g), value=[mid for _, mid in member_choices(ctx, g)]
            ),
            group,
            people,
        )
        save_btn.click(
            lambda i, c, a, sa: handle_category(ctx, i, c, a, sa),
            [txn_id, category, apply_all, show_all],
            [status, table],
        )
        confirm_btn.click(
            lambda i, sa: handle_confirm(ctx, i, sa), [txn_id, show_all], [status, table]
        )
        split_btn.click(
            lambda i, g, p, t, v, sa: handle_split(ctx, i, g, p, t, v, sa),
            [txn_id, group, people, split_type, values, show_all],
            [status, table],
        )
    return tab
