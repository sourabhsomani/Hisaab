"""Settings tab: rules, bank toggles, local LLM switch, budgets, export and backup."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import gradio as gr
import pandas as pd
from sqlmodel import select

from hisaab.core import models as m
from hisaab.core.db import backup_db
from hisaab.parsers.banks import discover
from hisaab.services import exporting
from hisaab.services.categories import category_name, category_names, delete_rule
from hisaab.services.importing import purge_raw_bodies
from hisaab.services.settings import set_budget
from hisaab.ui.common import Ctx, amount_input, err, ok

RULE_COLUMNS = ["id", "when", "contains", "category"]


def bank_names() -> list[str]:
    return [b.__name__.rsplit(".", 1)[1] for b in discover()]


def rules_table(ctx: Ctx) -> pd.DataFrame:
    with ctx.session() as s:
        rows = [
            {
                "id": r.id,
                "when": r.match_field.replace("_", " "),
                "contains": r.pattern,
                "category": category_name(s, r.category_id),
            }
            for r in s.exec(select(m.Rule).order_by(m.Rule.id.desc())).all()
        ]
    return pd.DataFrame(rows, columns=RULE_COLUMNS)


def handle_delete_rule(ctx: Ctx, rule_id):
    try:
        with ctx.session() as s:
            delete_rule(s, int(rule_id))
        msg = ok("Rule deleted.")
    except (TypeError, ValueError):
        msg = err("Type the rule id to delete.")
    return msg, rules_table(ctx)


def handle_save(
    ctx: Ctx, enabled_banks: list[str], llm_on: bool, llm_model: str, delete_raw: bool
) -> str:
    st = ctx.settings
    st.disabled_banks = sorted(set(bank_names()) - set(enabled_banks or []))
    st.llm_enabled = bool(llm_on)
    st.llm_model = (llm_model or st.llm_model).strip()
    st.delete_raw_sms = bool(delete_raw)
    ctx.save(st)
    msg = "Settings saved."
    if delete_raw:
        with ctx.session() as s:
            n = purge_raw_bodies(s)
        msg += f" Deleted the text of {n} stored SMS."
    return ok(msg)


def handle_budget(ctx: Ctx, category: str | None, amount) -> str:
    try:
        if not category:
            raise ValueError("pick a category")
        paise = 0 if str(amount).strip() in ("", "0") else amount_input(amount)
        ctx.save(set_budget(ctx.settings, category, paise))
        return ok(f"Budget for {category} {'removed' if not paise else 'saved'}.")
    except ValueError as exc:
        return err(str(exc))


def handle_export(ctx: Ctx, kind: str, out_dir: str | Path | None = None) -> str:
    """Write an export into a fresh temp folder and return its path for download."""
    folder = Path(out_dir or tempfile.mkdtemp(prefix="hisaab-"))
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    with ctx.session() as s:
        if kind == "csv":
            return str(exporting.export_transactions_csv(s, folder / f"hisaab-{stamp}.csv"))
        if kind == "json":
            return str(exporting.export_json(s, folder / f"hisaab-{stamp}.json"))
    if kind == "backup":
        return str(backup_db(ctx.engine, folder / f"hisaab-backup-{stamp}.db"))
    raise ValueError(f"unknown export: {kind}")


def build(ctx: Ctx) -> gr.Tab:
    st = ctx.settings
    with gr.Tab("Settings") as tab:
        gr.Markdown("### Rules\nCreated when you choose *Apply to all from this merchant*.")
        rules = gr.Dataframe(value=rules_table(ctx), headers=RULE_COLUMNS, interactive=False)
        with gr.Row():
            rule_id = gr.Number(label="Rule id", precision=0)
            del_btn = gr.Button("Delete rule", variant="stop")
        gr.Markdown("### Parsing")
        banks = gr.CheckboxGroup(
            bank_names(),
            label="Banks",
            value=[b for b in bank_names() if b not in st.disabled_banks],
        )
        llm_on = gr.Checkbox(
            value=st.llm_enabled,
            label="Use a local Ollama model for SMS "
            "the rules can't read (runs on this machine only)",
        )
        llm_model = gr.Textbox(value=st.llm_model, label="Ollama model")
        delete_raw = gr.Checkbox(
            value=st.delete_raw_sms, label="Delete SMS text after parsing (keeps only the fields)"
        )
        save_btn = gr.Button("Save settings", variant="primary")
        gr.Markdown("### Monthly budgets")
        with gr.Row():
            with ctx.session() as s:
                cats = category_names(s)
            b_cat = gr.Dropdown(cats, label="Category")
            b_amt = gr.Textbox(label="Budget (₹, 0 removes)")
            b_btn = gr.Button("Save budget")
        gr.Markdown("### Export and backup")
        with gr.Row():
            csv_btn = gr.Button("Transactions CSV")
            json_btn = gr.Button("Everything JSON")
            bak_btn = gr.Button("SQLite backup")
        out_file = gr.File(label="Download", interactive=False)
        status = gr.Markdown()

        tab.select(lambda: rules_table(ctx), None, rules)
        del_btn.click(lambda i: handle_delete_rule(ctx, i), rule_id, [status, rules])
        save_btn.click(
            lambda b, on, mdl, d: handle_save(ctx, b, on, mdl, d),
            [banks, llm_on, llm_model, delete_raw],
            status,
        )
        b_btn.click(lambda c, a: handle_budget(ctx, c, a), [b_cat, b_amt], status)
        csv_btn.click(lambda: handle_export(ctx, "csv"), None, out_file)
        json_btn.click(lambda: handle_export(ctx, "json"), None, out_file)
        bak_btn.click(lambda: handle_export(ctx, "backup"), None, out_file)
    return tab
