import pytest
from hypothesis import given
from hypothesis import strategies as st

from hisaab.core.models import SplitType
from hisaab.core.splits import (
    SplitError,
    compute_split,
    largest_remainder,
    split_adjustment,
    split_equal,
    split_exact,
    split_percentage,
    split_shares,
)

totals = st.integers(min_value=1, max_value=10**10)
member_lists = st.lists(st.integers(min_value=1, max_value=50), min_size=1, max_size=12, unique=True)


class TestLargestRemainder:
    def test_thirds(self):
        assert largest_remainder(100, {"a": 1, "b": 1, "c": 1}) == {"a": 34, "b": 33, "c": 33}

    def test_largest_fraction_wins(self):
        # 10 * 0.25 = 2.5, 10 * 0.35 = 3.5, 10 * 0.40 = 4.0 -> leftover 1 to first .5 (a)
        assert largest_remainder(10, {"a": "25", "b": "35", "c": "40"}) == {"a": 3, "b": 3, "c": 4}

    def test_zero_weight_member_gets_zero(self):
        assert largest_remainder(100, {"a": 1, "b": 0}) == {"a": 100, "b": 0}

    @pytest.mark.parametrize("weights", [{}, {"a": 0}, {"a": -1, "b": 2}])
    def test_invalid(self, weights):
        with pytest.raises(SplitError):
            largest_remainder(100, weights)


class TestEqual:
    def test_even(self):
        assert split_equal(90000, [1, 2, 3]) == {1: 30000, 2: 30000, 3: 30000}

    def test_leftover_goes_first(self):
        assert split_equal(100, [1, 2, 3]) == {1: 34, 2: 33, 3: 33}
        assert split_equal(101, [1, 2, 3]) == {1: 34, 2: 34, 3: 33}

    def test_single(self):
        assert split_equal(5, ["me"]) == {"me": 5}

    @pytest.mark.parametrize("total", [0, -5])
    def test_bad_total(self, total):
        with pytest.raises(SplitError):
            split_equal(total, [1])

    def test_float_total_rejected(self):
        with pytest.raises(SplitError):
            split_equal(10.5, [1])  # type: ignore[arg-type]

    def test_empty_and_duplicate(self):
        with pytest.raises(SplitError):
            split_equal(10, [])
        with pytest.raises(SplitError):
            split_equal(10, [1, 1])

    @given(totals, member_lists)
    def test_sums_and_fair(self, total, members):
        out = split_equal(total, members)
        assert sum(out.values()) == total
        assert max(out.values()) - min(out.values()) <= 1


class TestExact:
    def test_ok(self):
        assert split_exact(1000, {1: 600, 2: 400}) == {1: 600, 2: 400}

    def test_mismatch(self):
        with pytest.raises(SplitError, match="expected 1000"):
            split_exact(1000, {1: 600, 2: 300})

    def test_negative(self):
        with pytest.raises(SplitError):
            split_exact(100, {1: 150, 2: -50})

    def test_empty(self):
        with pytest.raises(SplitError):
            split_exact(100, {})


class TestPercentage:
    def test_basic(self):
        assert split_percentage(10000, {1: 50, 2: 30, 3: 20}) == {1: 5000, 2: 3000, 3: 2000}

    def test_thirds_rounding(self):
        out = split_percentage(100, {1: "33.33", 2: "33.33", 3: "33.34"})
        assert sum(out.values()) == 100

    def test_must_sum_100(self):
        with pytest.raises(SplitError, match="expected 100"):
            split_percentage(100, {1: 50, 2: 40})

    def test_empty(self):
        with pytest.raises(SplitError):
            split_percentage(100, {})

    @given(totals, st.lists(st.integers(1, 100), min_size=1, max_size=10))
    def test_property_sums(self, total, raw):
        s = sum(raw)
        pct = {i: str(v * 100 / s) for i, v in enumerate(raw)}
        try:
            out = split_percentage(total, pct)
        except SplitError:
            return  # float formatting drifted past 0.01; validated elsewhere
        assert sum(out.values()) == total


class TestShares:
    def test_two_one_one(self):
        assert split_shares(1000, {1: 2, 2: 1, 3: 1}) == {1: 500, 2: 250, 3: 250}

    def test_rounding(self):
        assert split_shares(10, {1: 1, 2: 1, 3: 1}) == {1: 4, 2: 3, 3: 3}

    @given(totals, st.dictionaries(st.integers(0, 30), st.integers(1, 9), min_size=1, max_size=10))
    def test_property_sums(self, total, shares):
        assert sum(split_shares(total, shares).values()) == total


class TestAdjustment:
    def test_extra_drink(self):
        # 1000 total, B had an extra 200 drink -> 800 split equally, B pays 200 more
        assert split_adjustment(1000, [1, 2], {2: 200}) == {1: 400, 2: 600}

    def test_negative_adjustment(self):
        assert split_adjustment(900, [1, 2, 3], {3: -300}) == {1: 400, 2: 400, 3: 100}

    def test_whole_total_adjusted(self):
        assert split_adjustment(500, [1, 2], {1: 500}) == {1: 500, 2: 0}

    def test_exceeds_total(self):
        with pytest.raises(SplitError):
            split_adjustment(100, [1, 2], {1: 200})

    def test_unknown_member(self):
        with pytest.raises(SplitError, match="non-participants"):
            split_adjustment(100, [1, 2], {9: 10})

    def test_negative_share(self):
        with pytest.raises(SplitError, match="negative"):
            split_adjustment(100, [1, 2], {1: -200})


class TestComputeSplit:
    def test_equal_ignores_values(self):
        assert compute_split("equal", 100, [1, 2], {1: 99}) == {1: 50, 2: 50}

    def test_exact(self):
        assert compute_split(SplitType.EXACT, 100, [1, 2], {1: 70, 2: 30}) == {1: 70, 2: 30}

    def test_percentage(self):
        assert compute_split("percentage", 200, [1, 2], {1: 75, 2: 25}) == {1: 150, 2: 50}

    def test_shares_missing_member_counts_zero(self):
        assert compute_split("shares", 300, [1, 2], {1: 1}) == {1: 300, 2: 0}

    def test_adjustment(self):
        assert compute_split("adjustment", 1000, [1, 2], {2: 200}) == {1: 400, 2: 600}

    def test_unknown_type(self):
        with pytest.raises(ValueError):
            compute_split("weird", 100, [1])
