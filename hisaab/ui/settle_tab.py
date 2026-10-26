"""Settle up tab: balances, fewest payments, UPI QR codes, WhatsApp text, auto-detected
repayments waiting for confirmation."""

from __future__ import annotations

import gradio as gr
import pandas as pd

from hisaab.core.models import SettlementStatus, Txn
from hisaab.core.money import format_inr
from hisaab.core.upi import qr_image
from hisaab.services import groups as gsvc
from hisaab.ui.common import Ctx, amount_input, err, group_choices, member_choices, ok

BALANCE_COLUMNS = ["member", "balance", "status"]
PLAN_COLUMNS = ["#", "pays", "to", "amount", "UPI link"]
PROPOSAL_COLUMNS = ["id", "group", "from", "to", "amount", "matched SMS"]


def balances_table(ctx: Ctx, group_id) -> pd.DataFrame:
    if not group_id:
        return pd.DataFrame(columns=BALANCE_COLUMNS)
    with ctx.session() as s:
        names = {x.id: x.name for x in gsvc.list_members(s, int(group_id))}
        rows = []
        for mid, bal in gsvc.group_balances(s, int(group_id)).items():
            state = "gets back" if bal > 0 else "owes" if bal < 0 else "settled"
            rows.append({"member": names[mid], "balance": format_inr(bal), "status": state})
    return pd.DataFrame(rows, columns=BALANCE_COLUMNS)


def plan_table(ctx: Ctx, group_id) -> pd.DataFrame:
    if not group_id:
        return pd.DataFrame(columns=PLAN_COLUMNS)
    with ctx.session() as s:
        lines = gsvc.payment_lines(s, int(group_id))
    rows = [
        {
            "#": i,
            "pays": ln.payer,
            "to": ln.payee,
            "amount": format_inr(ln.amount_paise),
            "UPI link": ln.link or "(no UPI ID)",
        }
        for i, ln in enumerate(lines, 1)
    ]
    return pd.DataFrame(rows, columns=PLAN_COLUMNS)


def summary_text(ctx: Ctx, group_id) -> str:
    if not group_id:
        return ""
    with ctx.session() as s:
        return gsvc.group_summary(s, int(group_id))


def qr_for(ctx: Ctx, group_id, number):
    """QR code image for payment ``number`` (1-based) of the plan, or ``None``."""
    if not group_id or not number:
        return None
    with ctx.session() as s:
        lines = gsvc.payment_lines(s, int(group_id))
    idx = int(number) - 1
    if not 0 <= idx < len(lines) or not lines[idx].link:
        return None
    return qr_image(lines[idx].link)


def proposals_table(ctx: Ctx) -> pd.DataFrame:
    with ctx.session() as s:
        rows = []
        for p in gsvc.list_settlements(s, status=SettlementStatus.PROPOSED):
            names = {x.id: x.name for x in gsvc.list_members(s, p.group_id)}
            txn = s.get(Txn, p.transaction_id) if p.transaction_id else None
            seen = (txn.counterparty_name or txn.counterparty_vpa or "") if txn else ""
            rows.append(
                {
                    "id": p.id,
                    "group": gsvc.get_group(s, p.group_id).name,
                    "from": names.get(p.from_member_id),
                    "to": names.get(p.to_member_id),
                    "amount": format_inr(p.amount_paise),
                    "matched SMS": seen,
                }
            )
    return pd.DataFrame(rows, columns=PROPOSAL_COLUMNS)


def handle_proposal(ctx: Ctx, settlement_id, accept: bool):
    try:
        with ctx.session() as s:
            if accept:
                gsvc.confirm_settlement(s, int(settlement_id))
            else:
                gsvc.reject_settlement(s, int(settlement_id))
        msg = ok("Marked as paid." if accept else "Dismissed.")
    except (TypeError, ValueError, LookupError):
        msg = err("Pick a proposed repayment by its id.")
    return msg, proposals_table(ctx)


def handle_manual(ctx: Ctx, group_id, from_id, to_id, amount):
    try:
        if not (group_id and from_id and to_id):
            raise ValueError("pick the group, who paid and who received")
        paise = amount_input(amount)
        with ctx.session() as s:
            gsvc.record_settlement(s, int(group_id), int(from_id), int(to_id), paise)
        msg = ok(f"Recorded {format_inr(paise)}.")
    except (ValueError, LookupError) as exc:
        msg = err(str(exc))
    return msg


def build(ctx: Ctx) -> gr.Tab:
    with gr.Tab("Settle up") as tab:
        gr.Markdown("### Repayments found in your SMS")
        proposals = gr.Dataframe(
            value=proposals_table(ctx), headers=PROPOSAL_COLUMNS, interactive=False
        )
        with gr.Row():
            prop_id = gr.Number(label="Repayment id", precision=0)
            yes_btn = gr.Button("Confirm paid", variant="primary")
            no_btn = gr.Button("Not this")
        group = gr.Dropdown(choices=group_choices(ctx), label="Group")
        balances = gr.Dataframe(headers=BALANCE_COLUMNS, interactive=False)
        gr.Markdown("#### Fewest payments to settle")
        plan = gr.Dataframe(headers=PLAN_COLUMNS, interactive=False, wrap=True)
        with gr.Row():
            qr_num = gr.Number(label="Payment #", value=1, precision=0)
            qr = gr.Image(label="Scan with any UPI app", type="pil", interactive=False)
        whatsapp = gr.Code(
            label="WhatsApp message (copy and send)", language="markdown", interactive=False
        )
        with gr.Accordion("Record a cash or other payment", open=False):
            with gr.Row():
                frm = gr.Dropdown(choices=[], label="Paid by")
                to = gr.Dropdown(choices=[], label="Paid to")
                amt = gr.Textbox(label="Amount (₹)")
            rec_btn = gr.Button("Record payment")
        status = gr.Markdown()

        def load(gid):
            choices = member_choices(ctx, gid)
            return (
                balances_table(ctx, gid),
                plan_table(ctx, gid),
                summary_text(ctx, gid),
                qr_for(ctx, gid, 1),
                gr.update(choices=choices),
                gr.update(choices=choices),
            )

        outs = [balances, plan, whatsapp, qr, frm, to]
        group.change(load, group, outs)
        tab.select(
            lambda: (proposals_table(ctx), gr.update(choices=group_choices(ctx))),
            None,
            [proposals, group],
        )
        qr_num.change(lambda g, n: qr_for(ctx, g, n), [group, qr_num], qr)
        yes_btn.click(lambda i: handle_proposal(ctx, i, True), prop_id, [status, proposals])
        no_btn.click(lambda i: handle_proposal(ctx, i, False), prop_id, [status, proposals])
        rec_btn.click(
            lambda g, f, t, a: handle_manual(ctx, g, f, t, a), [group, frm, to, amt], status
        ).then(load, group, outs)
    return tab
