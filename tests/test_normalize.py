import pytest

from hisaab.core.models import Direction
from hisaab.parsers.normalize import (
    canonical_merchant,
    known_brand,
    merchant_map,
    normalize_txn,
    strip_company_suffix,
    strip_gateway_prefix,
)
from hisaab.parsers.types import ParsedTxn


@pytest.mark.parametrize(
    "raw,clean",
    [
        ("RAZ*SWIGGY", "SWIGGY"),
        ("PYU*Zomato", "Zomato"),
        ("PTM*BLINKIT", "BLINKIT"),
        ("PAYTM-Zomato", "Zomato"),
        ("Razorpay * RAZ*Uber", "Uber"),
        ("RAHUL KUMAR", "RAHUL KUMAR"),
    ],
)
def test_strip_gateway_prefix(raw, clean):
    assert strip_gateway_prefix(raw) == clean


@pytest.mark.parametrize(
    "raw,clean",
    [
        ("Swiggy Pvt Ltd", "Swiggy"),
        ("Acme Private Limited", "Acme"),
        ("Foo Services India Pvt. Ltd.", "Foo"),
        ("Chai Point", "Chai Point"),
    ],
)
def test_strip_company_suffix(raw, clean):
    assert strip_company_suffix(raw) == clean


class TestCanonicalMerchant:
    def test_brand_merge(self):
        assert canonical_merchant("Swiggy Pvt Ltd") == "Swiggy"
        assert canonical_merchant("RAZ*SWIGGY") == "Swiggy"
        assert canonical_merchant("BUNDL TECHNOLOGIES") == "Swiggy"

    def test_unknown_is_title_cased(self):
        assert canonical_merchant("SHARMA TEA STALL") == "Sharma Tea Stall"

    def test_mixed_case_kept(self):
        assert canonical_merchant("McCafe Kota") == "McCafe Kota"

    def test_empty(self):
        assert canonical_merchant(None) is None
        assert canonical_merchant("") is None

    def test_custom_map(self):
        assert canonical_merchant("chai wala", {"Chai": {"keywords": ["chai"]}}) == "Chai"


def test_known_brand():
    assert known_brand("Swiggy")
    assert not known_brand("Sharma Tea Stall")
    assert not known_brand(None)


def test_merchant_map_loaded():
    assert merchant_map()["Swiggy"]["category"] == "Food"


class TestNormalizeTxn:
    def test_debit_brand_from_vpa(self):
        t = ParsedTxn(Direction.DEBIT, 100, counterparty_vpa="zomato@hdfcbank")
        assert normalize_txn(t).merchant == "Zomato"

    def test_debit_brand_from_merchant(self):
        t = ParsedTxn(Direction.DEBIT, 100, merchant="RAZ*SWIGGY")
        assert normalize_txn(t).merchant == "Swiggy"

    def test_debit_unknown_merchant_cleaned(self):
        t = ParsedTxn(Direction.DEBIT, 100, merchant="SHARMA TEA STALL")
        assert normalize_txn(t).merchant == "Sharma Tea Stall"

    def test_person_transfer_has_no_merchant(self):
        t = ParsedTxn(Direction.DEBIT, 100, counterparty_name="RAHUL KUMAR")
        out = normalize_txn(t)
        assert out.merchant is None and out.counterparty_name == "RAHUL KUMAR"

    def test_credit_keeps_name_only(self):
        t = ParsedTxn(Direction.CREDIT, 100, counterparty_name="PTM*RAHUL", merchant="x")
        out = normalize_txn(t)
        assert out.counterparty_name == "RAHUL" and out.merchant == "x"

    def test_original_untouched(self):
        t = ParsedTxn(Direction.DEBIT, 100, merchant="RAZ*SWIGGY")
        normalize_txn(t)
        assert t.merchant == "RAZ*SWIGGY"
