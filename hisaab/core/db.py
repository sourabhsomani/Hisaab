"""Database engine, schema creation, seeding and backup for the single SQLite file."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from hisaab.core import models
from hisaab.data import load_json

MEMORY = ":memory:"


def default_db_path() -> Path:
    """``$HISAAB_DB`` if set, otherwise ``~/.hisaab/hisaab.db``."""
    env = os.environ.get("HISAAB_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".hisaab" / "hisaab.db"


def _enable_foreign_keys(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def get_engine(path: str | Path | None = None) -> Engine:
    """Create an engine for ``path`` (``":memory:"`` for tests); parent folders are created."""
    target = str(path) if path is not None else str(default_db_path())
    if target == MEMORY:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{target}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def seed_categories(session: Session) -> int:
    """Insert default Indian categories that are missing. Returns the number added."""
    existing = {c.name for c in session.exec(select(models.Category)).all()}
    added = 0
    for item in load_json("categories.json"):
        if item["name"] not in existing:
            session.add(models.Category(name=item["name"], icon=item.get("icon", "")))
            added += 1
    session.commit()
    return added


def init_db(engine: Engine) -> None:
    """Create all tables and seed default categories (idempotent)."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        seed_categories(s)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Session that commits on success and rolls back on error."""
    with Session(engine, expire_on_commit=False) as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise


def sqlite_path(engine: Engine) -> str | None:
    """Filesystem path behind an engine, or ``None`` for in-memory databases."""
    db = engine.url.database
    return db if db and db != MEMORY else None


def backup_db(engine: Engine, dest: str | Path) -> Path:
    """Write a consistent copy of the database to ``dest`` using SQLite's backup API."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = engine.raw_connection()
    try:
        src = raw.driver_connection
        out = sqlite3.connect(dest)  # sqlite3's context manager commits but never closes
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        raw.close()
    return dest
