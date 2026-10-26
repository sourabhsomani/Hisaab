"""Import tab: paste SMS or upload SMS XML, bank statements and WhatsApp chats."""

from __future__ import annotations

from pathlib import Path

import gradio as gr
import pandas as pd
from rapidfuzz import fuzz

from hisaab.core.models import Source
from hisaab.core.money import format_inr
from hisaab.parsers.importers.sms_xml import parse_sms_xml, split_pasted
from hisaab.parsers.importers.statement_csv import import_statement
from hisaab.parsers.importers.whatsapp import parse_chat
from hisaab.services import groups as gsvc
from hisaab.services.importing import import_parsed
from hisaab.ui.common import Ctx, err, group_choices, make_pipeline, member_choices, ok

DRAFT_COLUMNS = ["add", "payer", "amount", "description", "date"]


def _report_text(report, proposals) -> str:
    lines = [ok(report.summary())]
    for p in proposals:
        lines.append(
            f"💸 Possible repayment found: {format_inr(p.amount_paise)} — confirm it "
            "in **Settle up**."
        )
    return "\n\n".join(lines)


def handle_paste(ctx: Ctx, text: str) -> str:
    messages = split_pasted(text or "")
    if not messages:
        return err("Paste one or more SMS first (separate messages with a blank line).")
    with ctx.session() as s:
        report, proposals = gsvc.import_and_propose(
            s,
            messages,
            source=Source.PASTE,
            pipeline=make_pipeline(s, ctx.settings),
            keep_raw=not ctx.settings.delete_raw_sms,
        )
    return _report_text(report, proposals)


def handle_upload(ctx: Ctx, file_path: str | None) -> str:
    """SMS Backup & Restore XML, or a CSV/Excel bank statement."""
    if not file_path:
        return err("Choose a file to upload.")
    suffix = Path(file_path).suffix.lower()
    try:
        with ctx.session() as s:
            if suffix == ".xml":
                messages = parse_sms_xml(Path(file_path))
                report, proposals = gsvc.import_and_propose(
                    s,
                    messages,
                    source=Source.XML,
                    pipeline=make_pipeline(s, ctx.settings),
                    keep_raw=not ctx.settings.delete_raw_sms,
                )
                return _report_text(report, proposals)
            if suffix in (".csv", ".xlsx", ".xls"):
                report = import_parsed(s, import_statement(file_path), source=Source.CSV)
                return _report_text(report, gsvc.propose_settlements(s, report.txn_ids))
    except Exception as exc:  # show file problems in the UI instead of crashing
        return err(f"Could not read that file: {exc}")
    return err(
        "Unsupported file. Use .xml (SMS backup), .csv/.xlsx (statement) or the "
        "WhatsApp box for .txt chats."
    )


def whatsapp_preview(file_path: str | None) -> tuple[pd.DataFrame, str]:
    if not file_path:
        return pd.DataFrame(columns=DRAFT_COLUMNS), err("Choose an exported chat (.txt).")
    text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    drafts = parse_chat(text)
    rows = [
        {
            "add": True,
            "payer": d.payer,
            "amount": d.amount_paise / 100,
            "description": d.description,
            "date": d.at.strftime("%Y-%m-%d %H:%M") if d.at else "",
        }
        for d in drafts
    ]
    note = (
        ok(
            f"Found {len(rows)} possible expenses. Untick any you don't want, pick a group, "
            "then add them."
        )
        if rows
        else err("No payments found in that chat.")
    )
    return pd.DataFrame(rows, columns=DRAFT_COLUMNS), note


def match_member(name: str, members: list[tuple[str, int]], threshold: float = 80) -> int | None:
    best, best_id = 0.0, None
    for label, mid in members:
        score = fuzz.WRatio(name.lower(), label.lower().removesuffix(" (me)"))
        if score > best:
            best, best_id = score, mid
    return best_id if best >= threshold else None


def whatsapp_add(ctx: Ctx, group_id: int | None, drafts: pd.DataFrame | None) -> str:
    """Add ticked drafts to a group, split equally among all members."""
    if not group_id:
        return err("Pick a group first.")
    if drafts is None or len(drafts) == 0:
        return err("Nothing to add.")
    members = member_choices(ctx, group_id)
    everyone = [mid for _, mid in members]
    added, skipped = 0, []
    with ctx.session() as s:
        for row in drafts.to_dict("records"):
            if str(row.get("add")).lower() not in ("true", "1", "yes"):
                continue
            payer = match_member(str(row["payer"]), members)
            if payer is None:
                skipped.append(str(row["payer"]))
                continue
            paise = round(float(row["amount"]) * 100)
            when = pd.to_datetime(row["date"]).to_pydatetime() if row.get("date") else None
            gsvc.add_expense(
                s, int(group_id), str(row["description"]), paise, payer, everyone, spent_at=when
            )
            added += 1
    msg = ok(f"Added {added} expenses, split equally.")
    if skipped:
        msg += f"\n\n{err('No member matched: ' + ', '.join(sorted(set(skipped))))}"
    return msg


SAMPLE = (
    "AX-HDFCBK:\nSent Rs.450.00 from HDFC Bank A/c **1234 to RAHUL KUMAR on 24/10/26. "
    "Ref 429812345678. Not You? Call your bank"
)


def build(ctx: Ctx) -> gr.Tab:
    with gr.Tab("Import") as tab:
        gr.Markdown(
            "### Paste bank SMS\nOne or many; put a blank line between messages. "
            "Optional first line with the sender, like `AX-HDFCBK:`."
        )
        paste = gr.Textbox(lines=8, label="SMS", placeholder=SAMPLE)
        paste_btn = gr.Button("Import SMS", variant="primary")
        paste_out = gr.Markdown()
        paste_btn.click(lambda t: handle_paste(ctx, t), paste, paste_out)

        with gr.Accordion("Upload SMS backup or bank statement", open=False):
            upload = gr.File(
                label="SMS Backup & Restore .xml, or statement .csv/.xlsx",
                file_types=[".xml", ".csv", ".xlsx", ".xls"],
                type="filepath",
            )
            upload_btn = gr.Button("Import file")
            upload_out = gr.Markdown()
            upload_btn.click(lambda f: handle_upload(ctx, f), upload, upload_out)

        with gr.Accordion("Import a WhatsApp group chat", open=False):
            chat = gr.File(
                label="Exported chat (.txt, without media)", file_types=[".txt"], type="filepath"
            )
            preview_btn = gr.Button("Find expenses")
            drafts = gr.Dataframe(
                headers=DRAFT_COLUMNS, interactive=True, wrap=True, label="Draft expenses"
            )
            wa_group = gr.Dropdown(choices=group_choices(ctx), label="Group")
            add_btn = gr.Button("Add ticked drafts to group")
            wa_out = gr.Markdown()
            preview_btn.click(whatsapp_preview, chat, [drafts, wa_out])
            add_btn.click(lambda g, d: whatsapp_add(ctx, g, d), [wa_group, drafts], wa_out)
        tab.select(lambda: gr.update(choices=group_choices(ctx)), None, wa_group)
    return tab
