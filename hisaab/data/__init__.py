"""Bundled data files (categories, merchant keywords, demo SMS)."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any


def load_json(name: str) -> Any:
    """Load a JSON file shipped inside ``hisaab/data``."""
    return json.loads(resources.files(__package__).joinpath(name).read_text(encoding="utf-8"))


def read_text(name: str) -> str:
    """Read a text file shipped inside ``hisaab/data``."""
    return resources.files(__package__).joinpath(name).read_text(encoding="utf-8")
