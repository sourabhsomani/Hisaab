from hisaab.core.models import Direction
from hisaab.parsers import generic
from hisaab.parsers.types import ParsedTxn


def test_parse_full_debit():
    t = generic.parse(
        "Sent Rs.450.00 from HDFC Bank A/c **1234 to RAHUL KUMAR on 24/10/26. Ref 429812345678."
    )
    assert t.direction is Direction.DEBIT
    assert t.amount_paise == 45000
    assert t.counterparty_name == "RAHUL KUMAR"
    assert t.confidence == generic.GENERIC_MAX_CONFIDENCE


def test_parse_needs_amount_and_direction():
    assert generic.parse("credited to your account") is None
    assert generic.parse("Rs.500 something") is None


def test_score_grows_with_fields():
    bare = ParsedTxn(Direction.DEBIT, 100)
    assert generic.score(bare) == 0.45
    rich = bare.copy(account_tail="1", upi_ref="1", counterparty_name="x")
    assert generic.score(rich) == 0.75


def test_score_capped():
    t = ParsedTxn(Direction.DEBIT, 100, "1", "x", None, "1", None)
    assert generic.score(t, base=0.95) == 1.0
