"""Bank plugins. Each module exposes ``SENDERS``, ``PATTERNS`` and ``parse(body)``.

Add a bank by dropping a new module here; ``discover()`` picks it up automatically.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType


def discover() -> list[ModuleType]:
    """Import every public bank module in this package, sorted by name."""
    mods = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        if hasattr(mod, "SENDERS") and hasattr(mod, "parse"):
            mods.append(mod)
    return mods
