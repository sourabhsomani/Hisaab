"""Groups tab: create groups, add members with UPI IDs, add or delete expenses."""

from __future__ import annotations

import gradio as gr
import pandas as pd

from hisaab.core.models import GroupKind
from hisaab.core.money import format_inr
from hisaab.services import groups as gsvc
from hisaab.ui.common import (
    Ctx,
    amount_input,
    err,
    group_choices,
    member_choices,
    ok,
    parse_values,
    values_for,
)

MEMBER_COLUMNS = ["id", "name", "UPI ID", "bank names (aliases)"]
EXPENSE_COLUMNS = ["id", "date", "description", "amount", "paid by", "split"]


def members_table(ctx: Ctx, group_id) -> pd.DataFrame:
    if not group_id:
        return pd.DataFrame(columns=MEMBER_COLUMNS)
    with ctx.session() as s:
        rows = [
            {
                "id": x.id,
                "name": x.name + (" (me)" if x.is_me else ""),
                "UPI ID": x.upi_vpa or "",
                "bank names (aliases)": x.aliases,
            }
            for x in gsvc.list_members(s, int(group_id))
        ]
    return pd.DataFrame(rows, columns=MEMBER_COLUMNS)


def expenses_table(ctx: Ctx, group_id) -> pd.DataFrame:
    if not group_id:
        return pd.DataFrame(columns=EXPENSE_COLUMNS)
    with ctx.session() as s:
        names = {x.id: x.name for x in gsvc.list_members(s, int(group_id))}
        rows = [
            {
                "id": e.id,
                "date": e.spent_at.strftime("%d %b %Y"),
                "description": e.description,
                "amount": format_inr(e.total_paise),
                "paid by": names.get(e.paid_by_member_id),
                "split": e.split_type.value,
            }
            for e in gsvc.list_expenses(s, int(group_id))
        ]
    return pd.DataFrame(rows, columns=EXPENSE_COLUMNS)


def handle_create_group(ctx: Ctx, name: str, kind: str, me: str, me_vpa: str = ""):
    try:
        with ctx.session() as s:
            grp = gsvc.create_group(
                s, name or "", kind or GroupKind.OTHER, (me or "Me").strip(), me_vpa
            )
            gid = grp.id
        return ok(f"Created {name.strip()}."), gr.update(choices=group_choices(ctx), value=gid)
    except ValueError as exc:
        return err(str(exc)), gr.update()


def handle_add_member(ctx: Ctx, group_id, name: str, vpa: str, aliases: str):
    try:
        if not group_id:
            raise ValueError("pick a group")
        with ctx.session() as s:
            gsvc.add_member(s, int(group_id), name or "", vpa, aliases=(aliases or "").strip())
        msg = ok(f"Added {name.strip()}.")
    except (ValueError, LookupError) as exc:
        msg = err(str(exc))
    return msg, members_table(ctx, group_id)


def handle_update_member(ctx: Ctx, group_id, member_id, vpa: str, aliases: str):
    """Set or clear a member's UPI ID and bank-name aliases (including your own)."""
    try:
        if not member_id:
            raise ValueError("pick a member")
        with ctx.session() as s:
            gsvc.update_member(s, int(member_id), upi_vpa=vpa, aliases=(aliases or "").strip())
        msg = ok("Member updated.")
    except (ValueError, LookupError) as exc:
        msg = err(str(exc))
    return msg, members_table(ctx, group_id)


def handle_add_expense(
    ctx: Ctx,
    group_id,
    description: str,
    amount,
    paid_by,
    participants,
    split_type: str,
    values_text: str,
):
    try:
        if not group_id:
            raise ValueError("pick a group")
        if not paid_by:
            raise ValueError("who paid?")
        if not participants:
            raise ValueError("pick who shared this expense")
        total = amount_input(amount)
        ids = [int(p) for p in participants]
        names = {mid: label for label, mid in member_choices(ctx, group_id)}
        values = values_for(split_type, parse_values(values_text, ids, names))
        with ctx.session() as s:
            gsvc.add_expense(
                s, int(group_id), description or "", total, int(paid_by), ids, split_type, values
            )
        msg = ok(f"Added {format_inr(total)} · {description or 'Expense'}.")
    except (ValueError, LookupError) as exc:
        msg = err(str(exc))
    return msg, expenses_table(ctx, group_id)


def handle_delete_expense(ctx: Ctx, group_id, expense_id):
    try:
        with ctx.session() as s:
            gsvc.delete_expense(s, int(expense_id))
        msg = ok("Deleted.")
    except (TypeError, ValueError, LookupError) as exc:
        msg = err(f"Could not delete: {exc}")
    return msg, expenses_table(ctx, group_id)


def build(ctx: Ctx) -> gr.Tab:
    with gr.Tab("Groups") as tab:
        group = gr.Dropdown(choices=group_choices(ctx), label="Group")
        with gr.Accordion("New group", open=not group_choices(ctx)):
            g_name = gr.Textbox(label="Name", placeholder="Goa trip")
            g_kind = gr.Radio([k.value for k in GroupKind], value="trip", label="Kind")
            g_me = gr.Textbox(label="Your name in this group", value="Me")
            g_vpa = gr.Textbox(
                label="Your UPI ID (so friends can pay you by QR)", placeholder="you@okicici"
            )
            g_btn = gr.Button("Create group", variant="primary")
        gr.Markdown("#### Members")
        members = gr.Dataframe(headers=MEMBER_COLUMNS, interactive=False)
        with gr.Row():
            m_name = gr.Textbox(label="Name")
            m_vpa = gr.Textbox(label="UPI ID (optional)", placeholder="rahul@okaxis")
            m_alias = gr.Textbox(label="Name as banks print it", placeholder="RAHUL KUM")
        m_btn = gr.Button("Add member")
        with gr.Accordion("Edit a member's UPI ID or bank names", open=False):
            u_member = gr.Dropdown(choices=[], label="Member")
            with gr.Row():
                u_vpa = gr.Textbox(label="UPI ID (blank clears it)")
                u_alias = gr.Textbox(label="Name as banks print it")
            u_btn = gr.Button("Save member")
        gr.Markdown("#### Add an expense")
        with gr.Row():
            e_desc = gr.Textbox(label="Description", placeholder="Dinner")
            e_amount = gr.Textbox(label="Amount (₹)", placeholder="1,200")
        with gr.Row():
            e_paid = gr.Dropdown(choices=[], label="Paid by")
            e_people = gr.Dropdown(choices=[], multiselect=True, label="Shared by")
        e_type = gr.Radio(
            ["equal", "exact", "percentage", "shares", "adjustment"], value="equal", label="Split"
        )
        e_values = gr.Textbox(
            label="Values (not for equal)",
            placeholder="exact ₹: Me=700, Rahul=500 · shares: 2, 1, 1",
        )
        e_btn = gr.Button("Add expense", variant="primary")
        expenses = gr.Dataframe(headers=EXPENSE_COLUMNS, interactive=False, wrap=True)
        with gr.Row():
            del_id = gr.Number(label="Expense id", precision=0)
            del_btn = gr.Button("Delete expense", variant="stop")
        status = gr.Markdown()

        def load(gid):
            choices = member_choices(ctx, gid)
            me = next((mid for label, mid in choices if label.endswith("(me)")), None)
            return (
                members_table(ctx, gid),
                expenses_table(ctx, gid),
                gr.update(choices=choices, value=me),
                gr.update(choices=choices, value=[mid for _, mid in choices]),
                gr.update(choices=choices, value=me),
            )

        group.change(load, group, [members, expenses, e_paid, e_people, u_member])
        tab.select(lambda: gr.update(choices=group_choices(ctx)), None, group)
        u_btn.click(
            lambda g, mid, v, a: handle_update_member(ctx, g, mid, v, a),
            [group, u_member, u_vpa, u_alias],
            [status, members],
        )
        g_btn.click(
            lambda n, k, me, v: handle_create_group(ctx, n, k, me, v),
            [g_name, g_kind, g_me, g_vpa],
            [status, group],
        )
        m_btn.click(
            lambda g, n, v, a: handle_add_member(ctx, g, n, v, a),
            [group, m_name, m_vpa, m_alias],
            [status, members],
        ).then(load, group, [members, expenses, e_paid, e_people, u_member])
        e_btn.click(
            lambda g, d, a, p, pp, t, v: handle_add_expense(ctx, g, d, a, p, pp, t, v),
            [group, e_desc, e_amount, e_paid, e_people, e_type, e_values],
            [status, expenses],
        )
        del_btn.click(
            lambda g, i: handle_delete_expense(ctx, g, i), [group, del_id], [status, expenses]
        )
    return tab
