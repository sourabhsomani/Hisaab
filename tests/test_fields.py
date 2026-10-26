from datetime import datetime

import pytest

from hisaab.core.models import Direction
from hisaab.parsers import fields as f

HDFC = "Sent Rs.450.00 from HDFC Bank A/c **1234 to RAHUL KUMAR on 24/10/26. Ref 429812345678."
SBI = (
    "Dear UPI user A/C X5678 credited by 450.00 on date 25Oct26 trf to RAHUL KUMAR "
    "Refno 429987654321 -SBI"
)


class TestAmount:
    @pytest.mark.parametrize(
        "body,expected",
        [
            (HDFC, 45000),
            (SBI, 45000),
            ("INR 1,23,456.00 debited", 12345600),
            ("₹99 paid to x", 9900),
            ("debited with 75.5 on", 7550),
        ],
    )
    def test_found(self, body, expected):
        assert f.find_amount(body) == expected

    def test_missing(self):
        assert f.find_amount("credited to your account") is None

    def test_zero_ignored(self):
        assert f.find_amount("Rs.0.00 debited") is None


class TestDirection:
    def test_debit(self):
        assert f.find_direction(HDFC) is Direction.DEBIT

    def test_credit(self):
        assert f.find_direction(SBI) is Direction.CREDIT

    def test_first_keyword_wins(self):
        assert f.find_direction("A/c debited Rs.5 and credited to Rahul") is Direction.DEBIT

    def test_refund_is_credit(self):
        assert f.find_direction("Refund of Rs.100 processed") is Direction.CREDIT

    def test_none(self):
        assert f.find_direction("hello") is None


class TestSimpleFields:
    @pytest.mark.parametrize(
        "body,tail",
        [
            (HDFC, "1234"),
            (SBI, "5678"),
            ("Card ending 9876 used", "9876"),
            ("Acct XX123456", "3456"),
        ],
    )
    def test_account_tail(self, body, tail):
        assert f.find_account_tail(body) == tail

    def test_account_tail_missing(self):
        assert f.find_account_tail("no account") is None

    def test_vpa(self):
        assert f.find_vpa("to VPA Rahul.K@OKAXIS on") == "rahul.k@okaxis"
        assert f.find_vpa("nothing") is None

    @pytest.mark.parametrize(
        "body,ref",
        [
            (HDFC, "429812345678"),
            (SBI, "429987654321"),
            ("UPI Ref No 529812345671", "529812345671"),
            ("UTR: 123456789012", "123456789012"),
            ("RRN 998877665544", "998877665544"),
        ],
    )
    def test_ref(self, body, ref):
        assert f.find_ref(body) == ref

    def test_ref_missing(self):
        assert f.find_ref("Ref 123") is None

    def test_balance(self):
        assert f.find_balance("Avl bal Rs.12,345.67") == 1234567
        assert f.find_balance("Available Balance: INR 500.00") == 50000
        assert f.find_balance("nothing") is None


class TestDates:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("on 24/10/26.", datetime(2026, 10, 24)),
            ("on 05-11-2026", datetime(2026, 11, 5)),
            ("date 25Oct26 trf", datetime(2026, 10, 25)),
            ("25-Oct-2026 at 18:05", datetime(2026, 10, 25, 18, 5)),
            ("on 05-11-2026 10:15 PM", datetime(2026, 11, 5, 22, 15)),
            ("on 2026-10-20:13:45:11.Avl", datetime(2026, 10, 20, 13, 45, 11)),
            ("01 Nov 2026", datetime(2026, 11, 1)),
        ],
    )
    def test_formats(self, text, expected):
        assert f.parse_sms_date(text) == expected

    def test_none(self):
        assert f.parse_sms_date("no date here") is None

    def test_invalid_date(self):
        assert f.parse_sms_date("on 45/13/26") is None


class TestNames:
    def test_clean_name(self):
        assert f.clean_name("  RAHUL   KUMAR. ") == "RAHUL KUMAR"
        assert f.clean_name("") is None
        assert f.clean_name(" . ") is None

    def test_counterparty_sent_to(self):
        assert f.find_counterparty(HDFC) == "RAHUL KUMAR"

    def test_counterparty_trf(self):
        assert f.find_counterparty(SBI) == "RAHUL KUMAR"

    def test_counterparty_skips_account(self):
        assert f.find_counterparty("Rs.5 credited to your a/c from PRIYA SHARMA on 1/1/26") == (
            "PRIYA SHARMA"
        )

    def test_counterparty_missing(self):
        assert f.find_counterparty("Rs.5 debited") is None

    def test_merchant(self):
        assert f.find_merchant("spent on Card x9876 at RAZ*SWIGGY on 20-10-26") == "RAZ*SWIGGY"
        assert f.find_merchant("no merchant") is None
