import pytest
from hypothesis import given
from hypothesis import strategies as st

from hisaab.core.settle import Payment, apply_payments, debts_for, net_balances, simplify_debts


class TestNetBalances:
    def test_single_expense(self):
        # A pays 900 for A, B, C equally
        bal = net_balances(paid=[("A", 900)], shares=[("A", 300), ("B", 300), ("C", 300)])
        assert bal == {"A": 600, "B": -300, "C": -300}

    def test_settlement_reduces_debt(self):
        bal = net_balances(
            paid=[("A", 900)],
            shares=[("A", 300), ("B", 300), ("C", 300)],
            settlements=[("B", "A", 300)],
        )
        assert bal == {"A": 300, "B": 0, "C": -300}

    def test_inactive_member_included(self):
        assert net_balances([], [], members=["Z"]) == {"Z": 0}

    def test_always_sums_to_zero(self):
        bal = net_balances(
            paid=[("A", 1000), ("B", 450)],
            shares=[("A", 500), ("B", 500), ("B", 225), ("C", 225)],
            settlements=[("C", "B", 100)],
        )
        assert sum(bal.values()) == 0


class TestSimplifyDebts:
    def test_simple(self):
        assert simplify_debts({"A": 600, "B": -300, "C": -300}) == [
            Payment("B", "A", 300),
            Payment("C", "A", 300),
        ]

    def test_chain_collapses(self):
        # A owes B 100, B owes C 100 -> A pays C directly
        assert simplify_debts({"A": -100, "B": 0, "C": 100}) == [Payment("A", "C", 100)]

    def test_largest_matched_first(self):
        out = simplify_debts({"A": 700, "B": 300, "C": -800, "D": -200})
        assert out[0] == Payment("C", "A", 700)
        assert sum(p.amount_paise for p in out) == 1000

    def test_all_settled(self):
        assert simplify_debts({"A": 0, "B": 0}) == []

    def test_empty(self):
        assert simplify_debts({}) == []

    def test_unbalanced(self):
        with pytest.raises(ValueError, match="off by 5"):
            simplify_debts({"A": 10, "B": -5})

    def test_deterministic_ties(self):
        a = simplify_debts({"A": 100, "B": 100, "C": -100, "D": -100})
        assert a == [Payment("C", "A", 100), Payment("D", "B", 100)]

    @given(st.lists(st.integers(-(10**8), 10**8), min_size=1, max_size=15))
    def test_property_settles_in_at_most_n_minus_1(self, values):
        balances = {i: v for i, v in enumerate(values)}
        balances[len(values)] = -sum(values)  # force zero-sum
        payments = simplify_debts(balances)
        assert all(v == 0 for v in apply_payments(balances, payments).values())
        assert len(payments) <= max(len(balances) - 1, 0)
        assert all(p.amount_paise > 0 for p in payments)


class TestHelpers:
    def test_apply_payments(self):
        assert apply_payments({"A": 100, "B": -100}, [Payment("B", "A", 100)]) == {"A": 0, "B": 0}

    def test_debts_for(self):
        plan = [Payment("B", "A", 300), Payment("C", "A", 200), Payment("A", "D", 50)]
        assert debts_for(plan, "A") == (50, 500)
        assert debts_for(iter(plan), "B") == (300, 0)
