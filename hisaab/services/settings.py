"""User settings stored as JSON next to the database (``~/.hisaab/settings.json``)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from hisaab.core.db import default_db_path


@dataclass
class Settings:
    llm_enabled: bool = False
    llm_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = "llama3.2"
    delete_raw_sms: bool = False
    budgets: dict[str, int] = field(default_factory=dict)  # category -> monthly paise
    disabled_banks: list[str] = field(default_factory=list)


def settings_path(db_path: Path | None = None) -> Path:
    return (db_path or default_db_path()).parent / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    """Read settings; missing file or unknown keys fall back to defaults."""
    path = path or settings_path()
    if not path.exists():
        return Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in data.items() if k in known})


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def set_budget(settings: Settings, category: str, paise: int) -> Settings:
    """Set (or with 0, remove) a monthly budget for a category."""
    if paise < 0:
        raise ValueError("budget cannot be negative")
    budgets = dict(settings.budgets)
    if paise == 0:
        budgets.pop(category, None)
    else:
        budgets[category] = paise
    settings.budgets = budgets
    return settings
