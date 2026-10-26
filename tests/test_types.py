from datetime import datetime

from hisaab.core.models import Direction
from hisaab.parsers.types import ParsedTxn


def test_copy_is_independent():
    a = ParsedTxn(Direction.DEBIT, 100)
    b = a.copy(amount_paise=5)
    assert a.amount_paise == 100 and b.amount_paise == 5


def test_as_dict():
    t = ParsedTxn(Direction.CREDIT, 100, "1234", "RAHUL", "r@ybl", "42", datetime(2026, 1, 2, 3, 4))
    assert t.as_dict() == {
        "direction": "credit",
        "amount_paise": 100,
        "account_tail": "1234",
        "counterparty_name": "RAHUL",
        "counterparty_vpa": "r@ybl",
        "upi_ref": "42",
        "txn_at": "2026-01-02T03:04:00",
    }


def test_as_dict_no_date():
    assert ParsedTxn(Direction.DEBIT, 1).as_dict()["txn_at"] is None
