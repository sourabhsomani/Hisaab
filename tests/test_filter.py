import pytest

from hisaab.parsers.filter import (
    classify_message,
    has_transaction_words,
    is_bank_sender,
    reject_reason,
)

DEBIT = "Sent Rs.450.00 from HDFC Bank A/c **1234 to RAHUL KUMAR on 24/10/26. Ref 429812345678."


class TestIsBankSender:
    @pytest.mark.parametrize("s", ["AX-HDFCBK", "JD-SBIUPI", "VM-ICICIT-S", "ax-hdfcbk", "", None])
    def test_allowed(self, s):
        assert is_bank_sender(s)

    @pytest.mark.parametrize("s", ["+919876543210", "Mom", "HDFCBK", "AX_HDFCBK"])
    def test_rejected(self, s):
        assert not is_bank_sender(s)


class TestRejectReason:
    @pytest.mark.parametrize(
        "body,reason",
        [
            ("123456 is your OTP for txn of Rs.500. Do not share", "otp"),
            ("Your one-time password is 4455", "otp"),
            ("Txn of Rs.300 to ZOMATO failed due to technical error", "failed"),
            ("Payment of Rs 200 declined at AMAZON", "failed"),
            ("Rahul has requested money Rs.250 from you on Google Pay", "request"),
            ("Collect request of Rs.99 from merchant@ybl", "request"),
            ("UPI Mandate created successfully for Netflix Rs.649", "mandate"),
            ("AutoPay set up for Spotify", "mandate"),
            ("Your credit card bill of Rs.4,500 is due on 05-11-26", "reminder"),
            ("Minimum amount due Rs.450", "reminder"),
            ("Pre-approved personal loan of Rs.5,00,000. Apply now!", "promo"),
            ("Get cashback up to Rs.100 on recharge", "promo"),
        ],
    )
    def test_reasons(self, body, reason):
        assert reject_reason(body) == reason

    def test_real_debit_passes(self):
        assert reject_reason(DEBIT) is None


class TestTransactionWords:
    def test_present(self):
        assert has_transaction_words("A/c credited with Rs.10")

    def test_absent(self):
        assert not has_transaction_words("Your statement is ready")


class TestClassify:
    def test_keep(self):
        assert classify_message("AX-HDFCBK", DEBIT) == (True, "ok")

    def test_empty(self):
        assert classify_message("AX-HDFCBK", "   ") == (False, "empty")

    def test_personal_sender(self):
        assert classify_message("+919999999999", DEBIT) == (False, "not_bank_sender")

    def test_no_transaction(self):
        assert classify_message("AX-HDFCBK", "Welcome to HDFC Bank NetBanking") == (
            False,
            "no_transaction",
        )

    def test_otp(self):
        assert classify_message("", "OTP 1234 for Rs.10 debit") == (False, "otp")
