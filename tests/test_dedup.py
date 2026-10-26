from datetime import datetime, timedelta

from hisaab.core.models import Direction
from hisaab.parsers.dedup import dedupe, is_same_payment, merge, message_hash
from hisaab.parsers.types import ParsedTxn

T0 = datetime(2026, 10, 24, 18, 30)


def txn(**kw):
    base = dict(direction=Direction.DEBIT, amount_paise=45000, account_tail="1234", txn_at=T0)
    base.update(kw)
    return ParsedTxn(**base)


class TestHash:
    def test_whitespace_and_case_insensitive(self):
        assert message_hash("ax-hdfcbk", "Sent  Rs.5\nto X") == message_hash(
            "AX-HDFCBK", "sent rs.5 to x"
        )

    def test_sender_matters(self):
        assert message_hash("AX-HDFCBK", "x") != message_hash("JD-SBIUPI", "x")

    def test_none_sender(self):
        assert message_hash(None, "x") == message_hash("", "x")


class TestSamePayment:
    def test_same_ref(self):
        assert is_same_payment(txn(upi_ref="1"), txn(upi_ref="1", amount_paise=1))

    def test_different_ref(self):
        assert not is_same_payment(txn(upi_ref="1"), txn(upi_ref="2"))

    def test_within_window(self):
        assert is_same_payment(txn(), txn(txn_at=T0 + timedelta(minutes=2)))

    def test_outside_window(self):
        assert not is_same_payment(txn(), txn(txn_at=T0 + timedelta(minutes=4)))

    def test_amount_or_direction_differs(self):
        assert not is_same_payment(txn(), txn(amount_paise=1))
        assert not is_same_payment(txn(), txn(direction=Direction.CREDIT))

    def test_needs_account_tail(self):
        assert not is_same_payment(txn(account_tail=None), txn(account_tail=None))
        assert not is_same_payment(txn(), txn(account_tail="9999"))

    def test_needs_time(self):
        assert not is_same_payment(txn(txn_at=None), txn())

    def test_date_only_same_day(self):
        assert is_same_payment(txn(txn_at=datetime(2026, 10, 24)), txn())
        assert not is_same_payment(txn(txn_at=datetime(2026, 10, 25)), txn())


class TestMerge:
    def test_fills_gaps(self):
        out = merge(txn(confidence=0.8), txn(counterparty_vpa="r@ybl", upi_ref="9", confidence=0.9))
        assert out.counterparty_vpa == "r@ybl" and out.upi_ref == "9"
        assert out.confidence == 0.9

    def test_primary_wins(self):
        assert merge(txn(merchant="A"), txn(merchant="B")).merchant == "A"


class TestDedupe:
    def test_bank_plus_app_sms_merge(self):
        bank = txn(upi_ref=None)
        app = txn(txn_at=T0 + timedelta(seconds=40), counterparty_vpa="rahul@okaxis")
        kept, merged = dedupe([bank, app])
        assert merged == 1 and len(kept) == 1
        assert kept[0].counterparty_vpa == "rahul@okaxis"

    def test_distinct_kept(self):
        kept, merged = dedupe([txn(upi_ref="1"), txn(upi_ref="2")])
        assert merged == 0 and len(kept) == 2
