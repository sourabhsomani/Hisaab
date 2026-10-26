import pytest

from hisaab.core.autosettle import (
    Debt,
    Identity,
    amount_fit,
    identity_score,
    match_credit,
    name_score,
)
from hisaab.core.models import Direction
from hisaab.parsers.types import ParsedTxn

ME = "me"
RAHUL = Identity("rahul", "Rahul Kumar", "rahul@okaxis", ("RAHUL KUM",))
PRIYA = Identity("priya", "Priya Sharma", None)
IDS = [RAHUL, PRIYA]


def credit(amount, name=None, vpa=None):
    return ParsedTxn(Direction.CREDIT, amount, counterparty_name=name, counterparty_vpa=vpa)


class TestNameScore:
    def test_exact_case_insensitive(self):
        assert name_score("RAHUL KUMAR", RAHUL) == 100

    def test_truncated_bank_name(self):
        assert name_score("RAHUL KUM", Identity(1, "Rahul Kumar")) >= 85

    def test_alias(self):
        assert name_score("RAHUL KUM", RAHUL) == 100

    def test_different_person(self):
        assert name_score("PRIYA SHARMA", RAHUL) < 85

    def test_dots_ignored(self):
        assert name_score("PRIYA.SHARMA", PRIYA) == 100

    def test_empty(self):
        assert name_score(None, RAHUL) == 0.0


class TestIdentityScore:
    def test_vpa_exact(self):
        assert identity_score(credit(1, vpa="RAHUL@okaxis"), RAHUL) == 100.0

    def test_vpa_mismatch_falls_back_to_name(self):
        assert identity_score(credit(1, "PRIYA SHARMA", "x@ybl"), PRIYA) == 100

    def test_nothing(self):
        assert identity_score(credit(1), RAHUL) == 0.0


class TestAmountFit:
    @pytest.mark.parametrize(
        "got,owed,expected",
        [
            (45000, 45000, (True, False)),
            (44950, 45000, (True, False)),  # within ₹1
            (45100, 45000, (True, False)),
            (20000, 45000, (True, True)),  # partial
            (46000, 45000, (False, False)),  # overpaid
            (0, 45000, (False, False)),
        ],
    )
    def test_cases(self, got, owed, expected):
        assert amount_fit(got, owed) == expected


class TestMatchCredit:
    def test_exact_name_and_amount(self):
        d = Debt("rahul", ME, 45000, "goa")
        p = match_credit(credit(45000, "RAHUL KUMAR"), [d], IDS)
        assert p.debt == d and p.amount_paise == 45000 and not p.partial

    def test_vpa_match(self):
        p = match_credit(credit(45000, vpa="rahul@okaxis"), [Debt("rahul", ME, 45000)], IDS)
        assert p.score == 100.0

    def test_small_rounding_settles_full_debt(self):
        p = match_credit(credit(44999, "RAHUL KUMAR"), [Debt("rahul", ME, 45000)], IDS)
        assert p.amount_paise == 45000

    def test_partial(self):
        p = match_credit(credit(20000, "RAHUL KUMAR"), [Debt("rahul", ME, 45000)], IDS)
        assert p.partial and p.amount_paise == 20000

    def test_below_threshold_never_matches(self):
        assert match_credit(credit(45000, "RAHUL SHARMA"), [Debt("rahul", ME, 45000)], IDS) is None

    def test_debit_ignored(self):
        t = ParsedTxn(Direction.DEBIT, 45000, counterparty_name="RAHUL KUMAR")
        assert match_credit(t, [Debt("rahul", ME, 45000)], IDS) is None

    def test_unknown_debtor_skipped(self):
        assert match_credit(credit(100, "X"), [Debt("ghost", ME, 100)], IDS) is None

    def test_overpayment_no_match(self):
        assert match_credit(credit(90000, "RAHUL KUMAR"), [Debt("rahul", ME, 45000)], IDS) is None

    def test_prefers_full_over_partial(self):
        debts = [Debt("rahul", ME, 90000, "flat"), Debt("rahul", ME, 45000, "goa")]
        p = match_credit(credit(45000, "RAHUL KUMAR"), debts, IDS)
        assert p.debt.group_id == "goa" and not p.partial

    def test_prefers_better_identity(self):
        twin = Identity("rahul2", "Rahul Kumarr")
        debts = [Debt("rahul2", ME, 45000), Debt("rahul", ME, 45000)]
        p = match_credit(credit(45000, "RAHUL KUMAR"), debts, [RAHUL, twin])
        assert p.debt.debtor == "rahul"

    def test_custom_threshold(self):
        p = match_credit(credit(45000, "RAHUL SHARMA"), [Debt("rahul", ME, 45000)], IDS, 60)
        assert p is not None
