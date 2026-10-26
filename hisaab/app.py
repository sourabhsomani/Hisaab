"""The gr.Blocks page: six tabs, each mapped to one job."""

from __future__ import annotations

import inspect
from pathlib import Path

import gradio as gr
from sqlalchemy.engine import Engine

from hisaab import __version__
from hisaab.core.db import get_engine, init_db
from hisaab.services.settings import settings_path
from hisaab.ui import groups_tab, import_tab, inbox_tab, insights_tab, settings_tab, settle_tab
from hisaab.ui.common import Ctx

TABS = (import_tab, inbox_tab, groups_tab, settle_tab, insights_tab, settings_tab)
CSS = ".gradio-container {max-width: 880px !important; margin: auto}"
HEADER = (
    "# Hisaab\n"
    "Your bank already texts you every payment. Hisaab turns those texts into splits, and "
    "tells you when your friends have paid you back. *Everything stays on this machine.*"
)
DEMO_BANNER = "> 🧪 **Demo mode** — synthetic data only, reset on restart. Do not paste real SMS."


def _theme_in_launch() -> bool:
    """Gradio 6 moved ``theme``/``css`` from ``Blocks()`` to ``launch()``."""
    return "theme" in inspect.signature(gr.Blocks.launch).parameters


def make_ctx(db_path: str | Path | None = None, demo: bool = False) -> Ctx:
    engine: Engine = get_engine(":memory:" if demo else db_path)
    init_db(engine)
    real = Path(db_path) if db_path and not demo else None
    return Ctx(engine=engine, settings_file=settings_path(real), demo=demo)


def build_app(ctx: Ctx) -> gr.Blocks:
    kwargs = {} if _theme_in_launch() else {"theme": gr.themes.Soft(), "css": CSS}
    with gr.Blocks(title="Hisaab", **kwargs) as app:
        gr.Markdown(HEADER)
        if ctx.demo:
            gr.Markdown(DEMO_BANNER)
        for tab in TABS:
            tab.build(ctx)
        gr.Markdown(f"<small>Hisaab {__version__} · AGPL-3.0 · no telemetry</small>")
    return app


def launch_kwargs(
    host: str = "127.0.0.1", port: int = 7860, password: str | None = None, demo: bool = False
) -> dict:
    """Safe launch options: never a share link; any non-loopback host needs a password,
    except the synthetic-data demo (e.g. on Hugging Face Spaces)."""
    if host not in ("127.0.0.1", "localhost", "::1") and not password and not demo:
        raise ValueError("exposing Hisaab beyond this machine needs --password")
    kwargs: dict = {"server_name": host, "server_port": port, "share": False}
    if password:
        kwargs["auth"] = ("hisaab", password)
    if _theme_in_launch():
        kwargs.update(theme=gr.themes.Soft(), css=CSS)
    return kwargs
