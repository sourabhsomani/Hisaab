import pytest
from hypothesis import given
from hypothesis import strategies as st

from hisaab.core.money import (
    format_inr,
    group_indian,
    paise_to_decimal_str,
    parse_amount,
    to_paise,
)


class TestToPaise:
    def test_string(self):
        assert to_paise("450.50") == 45050

    def test_int(self):
        assert to_paise(12) == 1200

    def test_rounds_half_up(self):
        assert to_paise("0.005") == 1
        assert to_paise("0.004") == 0

    def test_float_is_not_binary_rounded(self):
        assert to_paise(0.1 + 0.2) == 30

    def test_rejects_text(self):
        with pytest.raises(ValueError):
            to_paise("abc")


class TestParseAmount:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Rs.1,23,456.00", 12345600),
            ("INR 450", 45000),
            ("₹ 99.5", 9950),
            ("rs 1,000", 100000),
            ("450.00", 45000),
            ("Rs.0.50", 50),
            ("INR.12,00,000.75", 120000075),
        ],
    )
    def test_formats(self, text, expected):
        assert parse_amount(text) == expected

    def test_no_number(self):
        with pytest.raises(ValueError):
            parse_amount("Rs.")

    def test_none(self):
        with pytest.raises(ValueError):
            parse_amount(None)  # type: ignore[arg-type]


class TestGroupIndian:
    @pytest.mark.parametrize(
        "digits,expected",
        [
            ("0", "0"),
            ("999", "999"),
            ("1000", "1,000"),
            ("123456", "1,23,456"),
            ("1234567", "12,34,567"),
            ("123456789", "12,34,56,789"),
        ],
    )
    def test_grouping(self, digits, expected):
        assert group_indian(digits) == expected


class TestFormatInr:
    def test_lakh(self):
        assert format_inr(12345600) == "₹1,23,456.00"

    def test_small(self):
        assert format_inr(5) == "₹0.05"

    def test_negative(self):
        assert format_inr(-45000) == "-₹450.00"

    def test_without_symbol(self):
        assert format_inr(100000, symbol=False) == "1,000.00"

    @given(st.integers(min_value=0, max_value=10**13))
    def test_round_trips_through_parse(self, paise):
        assert parse_amount(format_inr(paise)) == paise


class TestPaiseToDecimalStr:
    def test_basic(self):
        assert paise_to_decimal_str(45000) == "450.00"

    def test_paise_only(self):
        assert paise_to_decimal_str(7) == "0.07"

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            paise_to_decimal_str(-1)
