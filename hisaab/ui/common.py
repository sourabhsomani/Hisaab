"""Shared UI helpers. Handlers in the tab modules are plain functions so they can be unit
tested without a browser; only ``build()`` functions touch Gradio components."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session

from hisaab.core.db import session_scope
from hisaab.core.money import format_inr, parse_amount
from hisaab.parsers.llm import LLMConfig, make_categorizer, make_extractor
from hisaab.parsers.pipeline import Pipeline, default_pipeline
from hisaab.services import groups as gsvc
from hisaab.services.categories import build_categorizer
from hisaab.services.settings import Settings, load_settings, save_settings


@dataclass
class Ctx:
    """What every handler needs: the database and where settings live."""

    engine: Engine
    settings_file: Path
    demo: bool = False
    _settings: Settings | None = field(default=None, repr=False)

    def session(self):
        return session_scope(self.engine)

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = load_settings(self.settings_file)
        return self._settings

    def save(self, settings: Settings) -> None:
        self._settings = settings
        if not self.demo:
            save_settings(settings, self.settings_file)


def make_pipeline(session: Session, settings: Settings) -> Pipeline:
    """Default pipeline minus disabled banks, plus the local LLM when switched on."""
    llm_cat = llm_ext = None
    if settings.llm_enabled:
        cfg = LLMConfig(base_url=settings.llm_url, model=settings.llm_model)
        llm_cat, llm_ext = make_categorizer(cfg), make_extractor(cfg)
    pipe = default_pipeline(
        categorizer=build_categorizer(session, llm=llm_cat), llm_extract=llm_ext
    )
    disabled = set(settings.disabled_banks)
    pipe.banks = [b for b in pipe.banks if b.__name__.rsplit(".", 1)[1] not in disabled]
    return pipe


def ok(text: str) -> str:
    return f"✅ {text}"


def err(text: str) -> str:
    return f"⚠️ {text}"


def rupees(paise: int | None) -> str:
    return "" if paise is None else format_inr(paise)


def amount_input(text: str | float | int | None) -> int:
    """Parse what the user typed in an amount box into paise."""
    if text is None or str(text).strip() == "":
        raise ValueError("enter an amount")
    paise = parse_amount(str(text))
    if paise <= 0:
        raise ValueError("amount must be more than zero")
    return paise


def group_choices(ctx: Ctx) -> list[tuple[str, int]]:
    with ctx.session() as s:
        return [(f"{grp.name} · {grp.kind.value}", grp.id) for grp in gsvc.list_groups(s)]


def member_choices(ctx: Ctx, group_id: int | None) -> list[tuple[str, int]]:
    if not group_id:
        return []
    with ctx.session() as s:
        return [
            (f"{mem.name} (me)" if mem.is_me else mem.name, mem.id)
            for mem in gsvc.list_members(s, int(group_id))
        ]


def parse_values(text: str | None, participants: list[int], names: dict[int, str]) -> dict:
    """Read split values typed as ``Rahul=2, Priya=1`` or positionally ``2, 1``.

    Exact and adjustment amounts are rupees (converted to paise); percentages and share
    counts stay as numbers. Returns ``{member_id: value_text}``.
    """
    if not text or not text.strip():
        return {}
    parts = [p.strip() for p in re.split(r"[,;\n]", text) if p.strip()]
    out: dict[int, str] = {}
    if all("=" in p or ":" in p for p in parts):
        lookup = {names[i].lower().removesuffix(" (me)"): i for i in participants}
        for p in parts:
            key, _, val = re.split(r"([=:])", p, maxsplit=1)
            key = key.strip().lower()
            mid = lookup.get(key) or next((i for k, i in lookup.items() if k.startswith(key)), None)
            if mid is None:
                raise ValueError(f"'{key}' is not a participant")
            out[mid] = val.strip()
        return out
    if len(parts) != len(participants):
        raise ValueError(f"expected {len(participants)} values, got {len(parts)}")
    return dict(zip(participants, parts, strict=True))


def values_for(split_type: str, raw: dict[int, str]) -> dict[int, float | int]:
    """Convert typed values: rupees -> paise for exact/adjustment, numbers otherwise."""
    out: dict[int, float | int] = {}
    for mid, val in raw.items():
        if split_type in ("exact", "adjustment"):
            neg = val.strip().startswith("-")
            paise = parse_amount(val.strip().lstrip("+-"))
            out[mid] = -paise if neg else paise
        else:
            out[mid] = float(val)
    return out
