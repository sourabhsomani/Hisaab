import json
from datetime import date, datetime

import pandas as pd
import pytest

from hisaab.core.models import Direction
from hisaab.parsers.pipeline import Message
from hisaab.parsers.types import ParsedTxn
from hisaab.services import exporting, insights
from hisaab.services import settings as st
from hisaab.services.importing import add_manual_txn, import_messages


def seed(session):
    add_manual_txn(
        session,
        ParsedTxn(Direction.DEBIT, 25000, merchant="Swiggy", txn_at=datetime(2026, 9, 5)),
        "Food",
    )
    add_manual_txn(
        session,
        ParsedTxn(Direction.DEBIT, 15000, merchant="Swiggy", txn_at=datetime(2026, 10, 1)),
        "Food",
    )
    add_manual_txn(
        session,
        ParsedTxn(Direction.DEBIT, 99900, merchant="Amazon", txn_at=datetime(2026, 10, 2)),
        "Shopping",
    )
    add_manual_txn(
        session,
        ParsedTxn(Direction.DEBIT, 50000, counterparty_name="RAHUL", txn_at=datetime(2026, 10, 3)),
        "Transfers",
    )
    add_manual_txn(
        session,
        ParsedTxn(Direction.CREDIT, 30000, counterparty_name="PRIYA", txn_at=datetime(2026, 10, 4)),
        "Transfers",
    )
    add_manual_txn(session, ParsedTxn(Direction.DEBIT, 100))  # no date, no category


class TestInsights:
    def test_current_month(self):
        assert insights.current_month(date(2026, 10, 26)) == "2026-10"
        assert len(insights.current_month()) == 7

    def test_txn_frame(self, session):
        seed(session)
        df = insights.txn_frame(session)
        assert list(df.columns) == insights.COLUMNS and len(df) == 6
        assert set(df["category"]) == {"Food", "Shopping", "Transfers", "Uncategorized"}
        assert df.loc[df["merchant"] == "Amazon", "amount"].item() == 999.0

    def test_empty_frames(self, session):
        assert insights.txn_frame(session).empty
        assert list(insights.monthly_spend(session).columns) == ["month", "spent", "received"]
        assert insights.spend_by_category(session).empty
        assert insights.top_merchants(session).empty

    def test_monthly_spend(self, session):
        seed(session)
        df = insights.monthly_spend(session)
        assert df.to_dict("records") == [
            {"month": "2026-09", "spent": 250.0, "received": 0.0},
            {"month": "2026-10", "spent": 1649.0, "received": 300.0},
        ]

    def test_monthly_spend_only_debits(self, session):
        add_manual_txn(session, ParsedTxn(Direction.DEBIT, 100, txn_at=datetime(2026, 1, 1)))
        assert insights.monthly_spend(session)["received"].tolist() == [0.0]

    def test_spend_by_category(self, session):
        seed(session)
        df = insights.spend_by_category(session, "2026-10")
        assert df.to_dict("records") == [
            {"category": "Shopping", "amount": 999.0},
            {"category": "Transfers", "amount": 500.0},
            {"category": "Food", "amount": 150.0},
        ]
        no_tr = insights.spend_by_category(session, "2026-10", exclude_transfers=True)
        assert "Transfers" not in set(no_tr["category"])

    def test_top_merchants(self, session):
        seed(session)
        df = insights.top_merchants(session)
        assert df.to_dict("records") == [
            {"merchant": "Amazon", "amount": 999.0, "count": 1},
            {"merchant": "Swiggy", "amount": 400.0, "count": 2},
        ]
        assert len(insights.top_merchants(session, limit=1)) == 1
        assert insights.top_merchants(session, "2026-09")["merchant"].tolist() == ["Swiggy"]

    def test_budget_status(self, session):
        seed(session)
        df = insights.budget_status(
            session, {"Food": 100000, "Health": 50000, "Zero": 0}, "2026-10"
        )
        food = df[df["category"] == "Food"].iloc[0]
        assert (food["budget"], food["spent"], food["left"], food["used"]) == (
            1000.0,
            150.0,
            850.0,
            0.15,
        )
        assert df[df["category"] == "Health"].iloc[0]["spent"] == 0.0
        assert df[df["category"] == "Zero"].iloc[0]["used"] == 0.0


class TestSettings:
    def test_defaults_when_missing(self, tmp_path):
        s = st.load_settings(tmp_path / "none.json")
        assert s == st.Settings() and not s.llm_enabled

    def test_round_trip(self, tmp_path):
        p = tmp_path / "s" / "settings.json"
        s = st.Settings(llm_enabled=True, budgets={"Food": 500000})
        st.save_settings(s, p)
        assert st.load_settings(p) == s

    def test_unknown_keys_and_bad_json(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text(json.dumps({"llm_model": "qwen", "future_option": 1}))
        assert st.load_settings(p).llm_model == "qwen"
        p.write_text("{nope")
        assert st.load_settings(p) == st.Settings()

    def test_settings_path(self, tmp_path, monkeypatch):
        assert st.settings_path(tmp_path / "x.db") == tmp_path / "settings.json"
        monkeypatch.setenv("HISAAB_DB", str(tmp_path / "h.db"))
        assert st.settings_path() == tmp_path / "settings.json"

    def test_set_budget(self):
        s = st.set_budget(st.Settings(), "Food", 100)
        assert s.budgets == {"Food": 100}
        assert st.set_budget(s, "Food", 0).budgets == {}
        with pytest.raises(ValueError):
            st.set_budget(s, "Food", -1)


class TestExport:
    def test_csv_has_no_raw_text(self, session, tmp_path):
        import_messages(
            session,
            [
                Message(
                    "AX-HDFCBK",
                    "Sent Rs.450.00 from HDFC Bank A/c **1234 to RAHUL KUMAR on 24/10/26. "
                    "Ref 429812345678.",
                )
            ],
        )
        path = exporting.export_transactions_csv(session, tmp_path / "out" / "t.csv")
        df = pd.read_csv(path)
        assert df["amount"].tolist() == [450.0]
        assert "Sent Rs" not in path.read_text()

    def test_json_all_tables_without_bodies(self, session, tmp_path):
        import_messages(session, [Message("AX-HDFCBK", "Rs.5 sent to RAHUL KUMAR from A/c XX1")])
        data = json.loads(exporting.export_json(session, tmp_path / "x.json").read_text())
        assert {
            "category",
            "transaction",
            "group",
            "member",
            "expense",
            "expense_share",
            "settlement",
            "rule",
            "raw_message",
        } <= set(data)
        assert "body" not in data["raw_message"][0]
        assert data["transaction"][0]["direction"] == "debit"

    def test_plain(self):
        assert exporting._plain(datetime(2026, 1, 1)) == "2026-01-01T00:00:00"
        assert exporting._plain(Direction.DEBIT) == "debit"
        assert exporting._plain(5) == 5
