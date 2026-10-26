from datetime import datetime

import pytest
from sqlmodel import select

from hisaab.core import models as m
from hisaab.core.models import Direction
from hisaab.parsers.pipeline import Message
from hisaab.parsers.types import ParsedTxn
from hisaab.services import categories as cats
from hisaab.services import importing as imp

HDFC = "Sent Rs.450.00 from HDFC Bank A/c **1234 to RAHUL KUMAR on 24/10/26. Ref 429812345678."
APP = "You paid Rs.450.00 to RAHUL KUMAR. UPI Ref No 429812345678"
SWIGGY = (
    "Spent Rs.250.00 On HDFC Bank Card 9876 At RAZ*SWIGGY On 2026-10-20:13:45:11 Bal Rs.12345.67"
)
ODD = "Rs.99 debited at XYZ 123"


def msgs(*bodies, sender="AX-HDFCBK"):
    return [Message(sender, b) for b in bodies]


class TestCategories:
    def test_names_and_ids(self, session):
        names = cats.category_names(session)
        assert "Food" in names and names == sorted(names)
        cid = cats.category_id(session, "food")
        assert cats.category_name(session, cid) == "Food"

    def test_unknown(self, session):
        assert cats.category_id(session, "Nope") is None
        assert cats.category_id(session, None) is None
        assert cats.category_name(session, None) is None
        assert cats.category_name(session, 9999) is None

    def test_add_category(self, session):
        c = cats.add_category(session, " Pets ", "🐶")
        assert c.name == "Pets"
        assert cats.add_category(session, "pets").id == c.id
        with pytest.raises(ValueError):
            cats.add_category(session, " ")

    def test_rule_target(self):
        assert cats.rule_target(
            m.Txn(direction=Direction.DEBIT, amount_paise=1, merchant="Swiggy")
        ) == ("merchant", "Swiggy")
        assert cats.rule_target(
            m.Txn(direction=Direction.DEBIT, amount_paise=1, counterparty_name="RAHUL")
        ) == ("counterparty_name", "RAHUL")
        assert cats.rule_target(m.Txn(direction=Direction.DEBIT, amount_paise=1)) is None


class TestImportMessages:
    def test_basic_counts(self, session):
        r = imp.import_messages(session, msgs(HDFC, SWIGGY, "Your OTP is 1234 for Rs.5 debit"))
        assert (r.total, r.parsed, r.ignored) == (3, 2, 1)
        txns = session.exec(select(m.Txn)).all()
        assert {t.amount_paise for t in txns} == {45000, 25000}
        food = cats.category_id(session, "Food")
        assert any(t.category_id == food and t.merchant == "Swiggy" for t in txns)
        assert "2 transactions" in r.summary()

    def test_reimport_is_noop(self, session):
        imp.import_messages(session, msgs(HDFC))
        r = imp.import_messages(session, msgs(HDFC, HDFC))
        assert r.already_imported == 2 and r.txn_ids == []
        assert "already imported" in r.summary()

    def test_bank_and_app_sms_one_txn_in_batch(self, session):
        r = imp.import_messages(session, [Message("AX-HDFCBK", HDFC), Message("JD-IPAYTM", APP)])
        assert r.duplicate == 1 and len(session.exec(select(m.Txn)).all()) == 1

    def test_dedup_against_earlier_import(self, session):
        imp.import_messages(session, [Message("AX-HDFCBK", HDFC)])
        r = imp.import_messages(session, [Message("JD-IPAYTM", APP)])
        assert r.duplicate == 1 and len(session.exec(select(m.Txn)).all()) == 1
        statuses = {x.status for x in session.exec(select(m.RawMessage)).all()}
        assert m.MessageStatus.DUPLICATE in statuses

    def test_review_items(self, session):
        r = imp.import_messages(session, msgs(ODD, "Your a/c was debited today", sender=""))
        assert r.review == 2
        assert len(imp.review_inbox(session)) == 1
        assert len(imp.unparsed_messages(session)) == 1

    def test_keep_raw_false(self, session):
        imp.import_messages(session, msgs(HDFC), keep_raw=False)
        assert session.exec(select(m.RawMessage)).one().body is None

    def test_received_at_and_source(self, session):
        when = datetime(2026, 10, 1, 9, 30)
        imp.import_messages(
            session,
            [Message("", "Rs.10 sent to RAHUL KUMAR from A/c XX1234", when)],
            source=m.Source.XML,
        )
        raw = session.exec(select(m.RawMessage)).one()
        assert raw.source == m.Source.XML and raw.received_at == when
        assert session.exec(select(m.Txn)).one().txn_at == when

    def test_uses_user_rules(self, session):
        imp.import_messages(session, msgs(ODD, sender=""))
        txn = session.exec(select(m.Txn)).one()
        cats.set_txn_category(session, txn.id, "Shopping", apply_to_all=True)
        imp.import_messages(
            session, msgs("Rs.15 debited at XYZ 123 from A/c XX1111 on 2/10/26", sender="")
        )
        newest = session.exec(select(m.Txn).order_by(m.Txn.id.desc())).first()
        assert cats.category_name(session, newest.category_id) == "Shopping"


class TestSetCategory:
    def test_single(self, session):
        imp.import_messages(session, msgs(ODD, sender=""))
        t = session.exec(select(m.Txn)).one()
        assert cats.set_txn_category(session, t.id, "Shopping") == 1
        assert t.confidence == 1.0
        assert session.exec(select(m.Rule)).all() == []

    def test_apply_to_all_creates_rule_and_updates_matches(self, session):
        imp.import_messages(session, msgs(ODD, "Rs.5 debited at XYZ 123 on 01/10/26", sender=""))
        first = session.exec(select(m.Txn)).first()
        assert cats.set_txn_category(session, first.id, "Shopping", apply_to_all=True) == 2
        rule = session.exec(select(m.Rule)).one()
        assert rule.match_field == "merchant" and rule.created_from_txn == first.id
        assert cats.load_rules(session)[0].category == "Shopping"
        cats.delete_rule(session, rule.id)
        assert cats.load_rules(session) == []
        cats.delete_rule(session, 999)  # no error

    def test_new_category_created(self, session):
        imp.import_messages(session, msgs(ODD, sender=""))
        t = session.exec(select(m.Txn)).one()
        cats.set_txn_category(session, t.id, "Gifts")
        assert "Gifts" in cats.category_names(session)

    def test_errors(self, session):
        with pytest.raises(LookupError):
            cats.set_txn_category(session, 999, "Food")
        t = imp.add_manual_txn(session, ParsedTxn(Direction.DEBIT, 100))
        with pytest.raises(ValueError):
            cats.set_txn_category(session, t.id, "Food", apply_to_all=True)


class TestOther:
    def test_import_parsed_dedupes(self, session):
        imp.import_messages(session, msgs(HDFC))
        stmt = [
            ParsedTxn(Direction.DEBIT, 45000, upi_ref="429812345678", confidence=0.9),
            ParsedTxn(Direction.DEBIT, 25000, merchant="Swiggy", confidence=0.9),
            ParsedTxn(Direction.DEBIT, 100, merchant="??", confidence=0.9),
        ]
        r = imp.import_parsed(session, stmt)
        assert (r.duplicate, r.parsed, r.review) == (1, 1, 1)

    def test_find_existing_without_time(self, session):
        imp.add_manual_txn(
            session,
            ParsedTxn(Direction.DEBIT, 500, account_tail="1", txn_at=datetime(2026, 1, 1, 10)),
        )
        assert imp.find_existing(session, ParsedTxn(Direction.DEBIT, 500, account_tail="1")) is None

    def test_confirm(self, session):
        t = imp.add_manual_txn(session, ParsedTxn(Direction.DEBIT, 100))
        t.confidence = 0.2
        assert imp.confirm_txn(session, t.id).confidence == 1.0
        with pytest.raises(LookupError):
            imp.confirm_txn(session, 999)

    def test_to_parsed_round_trip(self, session):
        t = imp.add_manual_txn(session, ParsedTxn(Direction.CREDIT, 7, upi_ref="1"))
        assert imp.to_parsed(t).upi_ref == "1"

    def test_purge_raw_bodies(self, session):
        imp.import_messages(session, msgs(HDFC, SWIGGY))
        assert imp.purge_raw_bodies(session) == 2
        assert imp.purge_raw_bodies(session) == 0
