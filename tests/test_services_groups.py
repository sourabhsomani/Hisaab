from datetime import datetime

import pytest
from sqlmodel import select

from hisaab.core import models as m
from hisaab.core.models import Direction, SettlementStatus
from hisaab.core.upi import parse_upi_link
from hisaab.parsers.pipeline import Message
from hisaab.parsers.types import ParsedTxn
from hisaab.services import groups as g
from hisaab.services.importing import add_manual_txn

CREDIT_SMS = (
    "Dear Customer, Acct XX321 is credited with Rs 300.00 on 25-Oct-26 from RAHUL KUMAR. "
    "UPI:529987654321-ICICI Bank."
)


@pytest.fixture
def trip(session):
    """Goa trip: me, Rahul (with UPI ID) and Priya."""
    grp = g.create_group(session, "Goa trip", "trip")
    me = g.get_me(session, grp.id)
    rahul = g.add_member(session, grp.id, "Rahul Kumar", "rahul@okaxis", aliases="RAHUL KUM")
    priya = g.add_member(session, grp.id, "Priya")
    return grp, me, rahul, priya


class TestGroups:
    def test_create_adds_owner(self, session):
        grp = g.create_group(session, " Flat 302 ", "flat")
        assert grp.name == "Flat 302" and grp.kind == m.GroupKind.FLAT
        me = g.get_me(session, grp.id)
        assert me.is_me and me.name == "Me"

    def test_create_with_owner_vpa(self, session):
        grp = g.create_group(session, "Trip", me="Sourabh", me_vpa=" me@okicici ")
        assert g.get_me(session, grp.id).upi_vpa == "me@okicici"
        with pytest.raises(ValueError, match="invalid UPI"):
            g.create_group(session, "Trip", me_vpa="nope")

    def test_create_validates(self, session):
        with pytest.raises(ValueError):
            g.create_group(session, "  ")
        with pytest.raises(ValueError):
            g.create_group(session, "x", "spaceship")

    def test_list_and_archive(self, session):
        a = g.create_group(session, "A")
        b = g.create_group(session, "B")
        assert [x.id for x in g.list_groups(session)] == [b.id, a.id]
        g.archive_group(session, a.id)
        assert [x.id for x in g.list_groups(session)] == [b.id]
        assert len(g.list_groups(session, include_archived=True)) == 2
        g.archive_group(session, a.id, archived=False)
        assert len(g.list_groups(session)) == 2

    def test_get_group_missing(self, session):
        with pytest.raises(LookupError):
            g.get_group(session, 999)

    def test_get_me_missing(self, session):
        grp = m.Group(name="raw")
        session.add(grp)
        session.commit()
        with pytest.raises(LookupError):
            g.get_me(session, grp.id)


class TestMembers:
    def test_add_and_list(self, session, trip):
        grp, me, rahul, priya = trip
        assert [x.name for x in g.list_members(session, grp.id)] == ["Me", "Rahul Kumar", "Priya"]
        assert rahul.alias_list() == ["RAHUL KUM"]

    def test_validation(self, session, trip):
        grp = trip[0]
        with pytest.raises(ValueError, match="invalid UPI"):
            g.add_member(session, grp.id, "X", "not-a-vpa")
        with pytest.raises(ValueError, match="already"):
            g.add_member(session, grp.id, "priya")
        with pytest.raises(ValueError):
            g.add_member(session, grp.id, " ")
        with pytest.raises(LookupError):
            g.add_member(session, 999, "Y")

    def test_blank_vpa_is_none(self, session, trip):
        assert g.add_member(session, trip[0].id, "Amit", "  ").upi_vpa is None

    def test_update(self, session, trip):
        priya = trip[3]
        g.update_member(session, priya.id, upi_vpa="priya@ybl", aliases="PRIYA S", bogus=1)
        assert priya.upi_vpa == "priya@ybl" and priya.aliases == "PRIYA S"
        with pytest.raises(ValueError):
            g.update_member(session, priya.id, upi_vpa="bad")
        g.update_member(session, priya.id, upi_vpa="  ")
        assert priya.upi_vpa is None
        with pytest.raises(LookupError):
            g.update_member(session, 999, name="x")


class TestExpenses:
    def test_equal_split_and_balances(self, session, trip):
        grp, me, rahul, priya = trip
        e = g.add_expense(session, grp.id, "Cab", 90000, me.id, [me.id, rahul.id, priya.id])
        assert g.expense_shares(session, e.id) == {me.id: 30000, rahul.id: 30000, priya.id: 30000}
        assert g.group_balances(session, grp.id) == {
            me.id: 60000,
            rahul.id: -30000,
            priya.id: -30000,
        }

    def test_shares_split_records_values(self, session, trip):
        grp, me, rahul, priya = trip
        e = g.add_expense(
            session,
            grp.id,
            "Villa",
            40000,
            rahul.id,
            [me.id, rahul.id],
            "shares",
            {me.id: 1, rahul.id: 3},
        )
        rows = session.exec(select(m.ExpenseShare).where(m.ExpenseShare.expense_id == e.id)).all()
        assert {r.member_id: (r.share_paise, r.share_value) for r in rows} == {
            me.id: (10000, 1.0),
            rahul.id: (30000, 3.0),
        }

    def test_blank_description(self, session, trip):
        grp, me = trip[0], trip[1]
        assert g.add_expense(session, grp.id, " ", 100, me.id, [me.id]).description == "Expense"

    def test_validation(self, session, trip):
        grp, me, rahul, _ = trip
        other = g.create_group(session, "Other")
        outsider = g.get_me(session, other.id)
        with pytest.raises(ValueError, match="payer"):
            g.add_expense(session, grp.id, "x", 100, outsider.id, [me.id])
        with pytest.raises(ValueError, match="participants"):
            g.add_expense(session, grp.id, "x", 100, me.id, [outsider.id])
        with pytest.raises(ValueError, match="participants"):
            g.add_expense(session, grp.id, "x", 100, me.id, [])

    def test_list_and_delete(self, session, trip):
        grp, me, rahul, _ = trip
        e1 = g.add_expense(
            session, grp.id, "a", 100, me.id, [me.id, rahul.id], spent_at=datetime(2026, 1, 1)
        )
        e2 = g.add_expense(
            session, grp.id, "b", 100, me.id, [me.id, rahul.id], spent_at=datetime(2026, 2, 1)
        )
        assert [e.id for e in g.list_expenses(session, grp.id)] == [e2.id, e1.id]
        g.delete_expense(session, e1.id)
        assert [e.id for e in g.list_expenses(session, grp.id)] == [e2.id]
        assert (
            session.exec(select(m.ExpenseShare).where(m.ExpenseShare.expense_id == e1.id)).all()
            == []
        )
        with pytest.raises(LookupError):
            g.delete_expense(session, e1.id)


class TestExpenseFromTxn:
    def test_split_imported_debit(self, session, trip):
        grp, me, rahul, priya = trip
        txn = add_manual_txn(
            session,
            ParsedTxn(Direction.DEBIT, 120000, merchant="Swiggy", txn_at=datetime(2026, 10, 20)),
        )
        e = g.expense_from_txn(session, txn.id, grp.id, [me.id, rahul.id, priya.id])
        assert e.paid_by_member_id == me.id and e.description == "Swiggy"
        assert e.transaction_id == txn.id and e.spent_at == datetime(2026, 10, 20)
        assert txn.is_split
        with pytest.raises(ValueError, match="already"):
            g.expense_from_txn(session, txn.id, grp.id, [me.id])
        g.delete_expense(session, e.id)
        assert not session.get(m.Txn, txn.id).is_split

    def test_rejects_credit_and_missing(self, session, trip):
        grp, me = trip[0], trip[1]
        credit = add_manual_txn(session, ParsedTxn(Direction.CREDIT, 100))
        with pytest.raises(ValueError, match="only money"):
            g.expense_from_txn(session, credit.id, grp.id, [me.id])
        with pytest.raises(LookupError):
            g.expense_from_txn(session, 999, grp.id, [me.id])


class TestSettlements:
    def test_plan_and_record(self, session, trip):
        grp, me, rahul, priya = trip
        g.add_expense(session, grp.id, "Cab", 90000, me.id, [me.id, rahul.id, priya.id])
        plan = g.settle_plan(session, grp.id)
        assert sorted((p.payer, p.amount_paise) for p in plan) == sorted(
            [(rahul.id, 30000), (priya.id, 30000)]
        )
        g.record_settlement(session, grp.id, rahul.id, me.id, 30000)
        assert g.group_balances(session, grp.id)[rahul.id] == 0
        assert len(g.settle_plan(session, grp.id)) == 1

    def test_proposed_does_not_change_balance(self, session, trip):
        grp, me, rahul, _ = trip
        g.add_expense(session, grp.id, "x", 200, me.id, [me.id, rahul.id])
        s = g.record_settlement(
            session, grp.id, rahul.id, me.id, 100, status=SettlementStatus.PROPOSED
        )
        assert g.group_balances(session, grp.id)[rahul.id] == -100
        g.confirm_settlement(session, s.id)
        assert g.group_balances(session, grp.id)[rahul.id] == 0
        assert g.list_settlements(session, grp.id, SettlementStatus.CONFIRMED) == [s]

    def test_reject(self, session, trip):
        grp, me, rahul, _ = trip
        s = g.record_settlement(
            session, grp.id, rahul.id, me.id, 100, status=SettlementStatus.PROPOSED
        )
        assert g.reject_settlement(session, s.id).status == SettlementStatus.REJECTED
        with pytest.raises(LookupError):
            g.confirm_settlement(session, 999)

    def test_validation(self, session, trip):
        grp, me, rahul, _ = trip
        with pytest.raises(ValueError):
            g.record_settlement(session, grp.id, rahul.id, me.id, 0)
        with pytest.raises(ValueError):
            g.record_settlement(session, grp.id, me.id, me.id, 10)
        with pytest.raises(ValueError):
            g.record_settlement(session, grp.id, me.id, 999, 10)

    def test_list_all(self, session, trip):
        grp, me, rahul, _ = trip
        g.record_settlement(session, grp.id, rahul.id, me.id, 5)
        assert len(g.list_settlements(session)) == 1


class TestAutoSettle:
    def test_full_loop(self, session, trip):
        """Split -> friend pays via UPI -> credit SMS -> proposed -> confirmed -> settled."""
        grp, me, rahul, priya = trip
        g.add_expense(session, grp.id, "Cab", 90000, me.id, [me.id, rahul.id, priya.id])
        report, proposals = g.import_and_propose(session, [Message("VM-ICICIT", CREDIT_SMS)])
        assert report.parsed == 1
        (p,) = proposals
        assert (p.from_member_id, p.to_member_id, p.amount_paise) == (rahul.id, me.id, 30000)
        assert p.status == SettlementStatus.PROPOSED and p.method == m.SettlementMethod.UPI_SMS
        g.confirm_settlement(session, p.id)
        assert g.group_balances(session, grp.id)[rahul.id] == 0

    def test_partial_payment(self, session, trip):
        grp, me, rahul, _ = trip
        g.add_expense(session, grp.id, "Villa", 200000, me.id, [me.id, rahul.id])
        _, (p,) = g.import_and_propose(session, [Message("VM-ICICIT", CREDIT_SMS)])
        assert p.amount_paise == 30000

    def test_vpa_match_and_no_double_proposal(self, session, trip):
        grp, me, rahul, _ = trip
        g.add_expense(session, grp.id, "x", 60000, me.id, [me.id, rahul.id])
        t = add_manual_txn(
            session, ParsedTxn(Direction.CREDIT, 30000, counterparty_vpa="rahul@okaxis")
        )
        assert len(g.propose_settlements(session, [t.id])) == 1
        assert g.propose_settlements(session, [t.id]) == []

    def test_already_proposed_amount_is_subtracted(self, session, trip):
        grp, me, rahul, _ = trip
        g.add_expense(session, grp.id, "x", 60000, me.id, [me.id, rahul.id])
        g.record_settlement(
            session, grp.id, rahul.id, me.id, 30000, status=SettlementStatus.PROPOSED
        )
        debts, _ = g.pending_debts_to_me(session)
        assert debts == []

    def test_ignores_debits_unknown_and_strangers(self, session, trip):
        grp, me, rahul, _ = trip
        g.add_expense(session, grp.id, "x", 60000, me.id, [me.id, rahul.id])
        d = add_manual_txn(session, ParsedTxn(Direction.DEBIT, 30000, counterparty_name="RAHUL"))
        s = add_manual_txn(
            session, ParsedTxn(Direction.CREDIT, 30000, counterparty_name="ZZ STRANGER")
        )
        assert g.propose_settlements(session, [d.id, s.id, 999]) == []

    def test_debts_only_to_me(self, session, trip):
        grp, me, rahul, priya = trip
        g.add_expense(session, grp.id, "x", 60000, rahul.id, [rahul.id, priya.id])
        debts, identities = g.pending_debts_to_me(session)
        assert debts == [] and {i.name for i in identities} == {"Rahul Kumar", "Priya"}


class TestSharing:
    def test_payment_lines_and_summary(self, session, trip):
        grp, me, rahul, priya = trip
        g.add_expense(session, grp.id, "Cab", 90000, rahul.id, [me.id, rahul.id, priya.id])
        lines = g.payment_lines(session, grp.id)
        assert {(ln.payer, ln.payee, ln.amount_paise) for ln in lines} == {
            ("Me", "Rahul Kumar", 30000),
            ("Priya", "Rahul Kumar", 30000),
        }
        params = parse_upi_link(lines[0].link)
        assert params["pa"] == "rahul@okaxis" and params["tn"] == "Hisaab Goa trip"
        text = g.group_summary(session, grp.id)
        assert "*Hisaab · Goa trip*" in text and "upi://pay" in text

    def test_owner_gets_qr_links(self, session):
        grp = g.create_group(session, "Flat", me_vpa="me@okicici")
        me = g.get_me(session, grp.id)
        roomie = g.add_member(session, grp.id, "Kabir")
        g.add_expense(session, grp.id, "Wi-Fi", 100000, me.id, [me.id, roomie.id])
        (line,) = g.payment_lines(session, grp.id)
        assert parse_upi_link(line.link)["pa"] == "me@okicici"

    def test_no_link_without_vpa(self, session, trip):
        grp, me, rahul, priya = trip
        g.add_expense(session, grp.id, "x", 200, priya.id, [me.id, priya.id])
        (line,) = g.payment_lines(session, grp.id, note="custom")
        assert line.link is None

    def test_settled_summary(self, session, trip):
        assert "All settled up" in g.group_summary(session, trip[0].id)
