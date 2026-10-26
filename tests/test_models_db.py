import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from hisaab.core import models as m
from hisaab.core.db import (
    backup_db,
    default_db_path,
    get_engine,
    init_db,
    seed_categories,
    session_scope,
    sqlite_path,
)
from hisaab.data import load_json, read_text


class TestPaths:
    def test_default_path_in_home(self, monkeypatch):
        monkeypatch.delenv("HISAAB_DB", raising=False)
        assert default_db_path() == Path.home() / ".hisaab" / "hisaab.db"

    def test_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HISAAB_DB", str(tmp_path / "x.db"))
        assert default_db_path() == tmp_path / "x.db"


class TestEngine:
    def test_file_engine_creates_parent(self, tmp_path):
        path = tmp_path / "nested" / "h.db"
        eng = get_engine(path)
        init_db(eng)
        assert path.exists()
        assert sqlite_path(eng) == str(path)

    def test_memory_has_no_path(self, engine):
        assert sqlite_path(engine) is None

    def test_foreign_keys_enforced(self, session):
        session.add(m.Member(group_id=999, name="Ghost"))
        with pytest.raises(IntegrityError):
            session.commit()


class TestSeeding:
    def test_init_seeds_defaults(self, session):
        names = {c.name for c in session.exec(select(m.Category)).all()}
        assert {"Food", "Groceries", "Rent", "Fuel", "Travel", "Bills", "Shopping"} <= names

    def test_seed_is_idempotent(self, session):
        assert seed_categories(session) == 0

    def test_init_twice_is_safe(self, engine):
        init_db(engine)
        with Session(engine) as s:
            assert len(s.exec(select(m.Category)).all()) == len(load_json("categories.json"))


class TestSessionScope:
    def test_commits(self, engine):
        with session_scope(engine) as s:
            s.add(m.Group(name="Goa"))
        with Session(engine) as s:
            assert s.exec(select(m.Group)).one().name == "Goa"

    def test_rolls_back(self, engine):
        with pytest.raises(RuntimeError), session_scope(engine) as s:
            s.add(m.Group(name="Nope"))
            s.flush()
            raise RuntimeError("boom")
        with Session(engine) as s:
            assert s.exec(select(m.Group)).all() == []


class TestModels:
    def test_alias_list(self):
        mem = m.Member(group_id=1, name="Rahul", aliases="RAHUL KUM, R KUMAR,,")
        assert mem.alias_list() == ["RAHUL KUM", "R KUMAR"]

    def test_alias_list_empty(self):
        assert m.Member(group_id=1, name="x").alias_list() == []

    def test_raw_message_hash_unique(self, session):
        session.add(m.RawMessage(hash="abc", body="x"))
        session.add(m.RawMessage(hash="abc", body="y"))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_full_graph(self, session):
        g = m.Group(name="Flat", kind=m.GroupKind.FLAT)
        session.add(g)
        session.commit()
        a = m.Member(group_id=g.id, name="A", is_me=True)
        b = m.Member(group_id=g.id, name="B")
        session.add_all([a, b])
        session.commit()
        e = m.Expense(
            group_id=g.id, description="Wi-Fi", total_paise=100000, paid_by_member_id=a.id
        )
        session.add(e)
        session.commit()
        session.add(m.ExpenseShare(expense_id=e.id, member_id=b.id, share_paise=50000))
        session.add(m.Settlement(group_id=g.id, from_member_id=b.id, to_member_id=a.id,
                                 amount_paise=50000))
        session.commit()
        assert session.exec(select(m.Settlement)).one().status == m.SettlementStatus.CONFIRMED

    def test_now_is_naive(self):
        assert m.now().tzinfo is None
        assert m.now().microsecond == 0

    def test_datetimes_round_trip_naive(self, session):
        from datetime import datetime

        when = datetime(2026, 10, 24, 18, 30)
        session.add(m.RawMessage(hash="h1", body="x", received_at=when))
        session.commit()
        got = session.exec(select(m.RawMessage)).one().received_at
        assert got == when and got.tzinfo is None


class TestBackup:
    def test_backup_copies_rows(self, engine, tmp_path):
        with session_scope(engine) as s:
            s.add(m.Group(name="Trip"))
        out = backup_db(engine, tmp_path / "b" / "backup.db")
        with sqlite3.connect(out) as conn:
            assert conn.execute('select name from "group"').fetchone() == ("Trip",)


class TestDataLoader:
    def test_read_text(self):
        assert "Food" in read_text("categories.json")
