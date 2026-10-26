"""Insights tab: monthly spend, categories, merchants and budgets."""

from __future__ import annotations

import gradio as gr

from hisaab.core.money import format_inr
from hisaab.services import insights as ins
from hisaab.ui.common import Ctx


def months(ctx: Ctx) -> list[str]:
    with ctx.session() as s:
        ms = ins.monthly_spend(s)["month"].tolist()
    return list(reversed(ms)) or [ins.current_month()]


def insights_data(ctx: Ctx, month: str | None):
    month = month or months(ctx)[0]
    with ctx.session() as s:
        monthly = ins.monthly_spend(s)
        cats = ins.spend_by_category(s, month)
        merchants = ins.top_merchants(s, month)
        budgets = ins.budget_status(s, ctx.settings.budgets, month)
    spent = cats["amount"].sum() if not cats.empty else 0
    headline = f"### {format_inr(round(spent * 100))} spent in {month}"
    if not budgets.empty:
        over = budgets[budgets["left"] < 0]["category"].tolist()
        headline += f"\n⚠️ Over budget: {', '.join(over)}" if over else "\nAll budgets on track ✅"
    view = budgets.copy()
    for col in ("budget", "spent", "left"):
        view[col] = [format_inr(round(v * 100)) for v in view[col]]
    view["used"] = [f"{u:.0%}" for u in view["used"]]
    return headline, monthly, cats, merchants, view


def build(ctx: Ctx) -> gr.Tab:
    with gr.Tab("Insights") as tab:
        month = gr.Dropdown(choices=months(ctx), value=months(ctx)[0], label="Month")
        headline = gr.Markdown()
        monthly = gr.BarPlot(x="month", y="spent", title="Spent per month (₹)")
        cats = gr.BarPlot(x="category", y="amount", title="By category (₹)", sort="-y")
        merchants = gr.Dataframe(label="Top merchants", interactive=False)
        budgets = gr.Dataframe(label="Budgets (set them in Settings)", interactive=False)
        outs = [headline, monthly, cats, merchants, budgets]
        month.change(lambda mo: insights_data(ctx, mo), month, outs)
        tab.select(
            lambda mo: (gr.update(choices=months(ctx)), *insights_data(ctx, mo)),
            month,
            [month, *outs],
        )
    return tab
