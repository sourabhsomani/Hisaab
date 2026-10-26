import types
from datetime import datetime

from hisaab.core.models import Direction
from hisaab.parsers.categorize import Categorizer, CategoryRule
from hisaab.parsers.pipeline import Message, Pipeline, _sender_matches, summarize
from hisaab.parsers.types import ParsedTxn, ParseResult, ResultStatus

HDFC = "Sent Rs.450.00 from HDFC Bank A/c **1234 to RAHUL KUMAR on 24/10/26. Ref 429812345678."


def fake_bank(senders, result):
    mod = types.ModuleType("fakebank")
    mod.SENDERS = senders
    mod.calls = []

    def parse(body):
        mod.calls.append(body)
        return result

    mod.parse = parse
    return mod


def test_sender_matches():
    assert _sender_matches("AX-HDFCBK", ["HDFCBK"])
    assert not _sender_matches("", ["HDFCBK"])


class TestExtract:
    def test_matching_bank_first(self):
        hit = ParsedTxn(Direction.DEBIT, 1, confidence=0.99)
        other = fake_bank(["SBI"], ParsedTxn(Direction.DEBIT, 2))
        mine = fake_bank(["HDFCBK"], hit)
        assert Pipeline(banks=[other, mine]).extract("AX-HDFCBK", HDFC) is hit
        assert other.calls == []

    def test_falls_back_to_other_banks_then_generic(self):
        none_bank = fake_bank(["X"], None)
        t = Pipeline(banks=[none_bank]).extract("AX-HDFCBK", HDFC)
        assert t.amount_paise == 45000 and none_bank.calls == [HDFC]

    def test_llm_last(self):
        llm_txn = ParsedTxn(Direction.DEBIT, 7)
        p = Pipeline(llm_extract=lambda b: llm_txn)
        assert p.extract("", "weird debited message") is llm_txn

    def test_llm_error_ignored(self):
        def boom(body):
            raise RuntimeError

        assert Pipeline(llm_extract=boom).extract("", "nothing debited") is None


class TestProcess:
    def test_parsed(self):
        r = Pipeline().process("AX-HDFCBK", HDFC)
        assert r.status is ResultStatus.PARSED
        assert r.category == "Transfers"
        assert r.txn.counterparty_name == "RAHUL KUMAR"

    def test_ignored(self):
        r = Pipeline().process("AX-HDFCBK", "Your OTP is 1234 for Rs.5 debit")
        assert r.status is ResultStatus.IGNORED and r.reason == "otp"

    def test_unparsed_goes_to_review(self):
        r = Pipeline().process("AX-HDFCBK", "Your a/c was debited today")
        assert r.status is ResultStatus.REVIEW and r.reason == "unparsed"

    def test_low_confidence_review(self):
        r = Pipeline().process("", "Rs.99 debited at XYZ 123")
        assert r.status is ResultStatus.REVIEW and r.reason == "low_confidence"

    def test_rule_lifts_confidence(self):
        cat = Categorizer(rules=[CategoryRule("merchant", "XYZ", "Shopping")])
        r = Pipeline(categorizer=cat).process(
            "", "Rs.99 debited from A/c XX1234 at XYZ 123 on 01/10/26"
        )
        assert r.category == "Shopping" and r.status is ResultStatus.PARSED

    def test_received_at_fills_missing_date(self):
        when = datetime(2026, 10, 1, 9, 0)
        r = Pipeline().process("", "Rs.10 sent to RAHUL KUMAR from A/c XX1234", when)
        assert r.txn.txn_at == when

    def test_custom_threshold(self):
        r = Pipeline(threshold=0.99).process("AX-HDFCBK", HDFC)
        assert r.status is ResultStatus.REVIEW


class TestProcessMany:
    def test_marks_second_sms_duplicate(self):
        msgs = [
            Message("AX-HDFCBK", HDFC),
            Message("VM-PAYTMB", "You paid Rs.450.00 to RAHUL KUMAR. UPI Ref No 429812345678"),
            Message("AX-HDFCBK", "Your OTP is 99"),
        ]
        results = Pipeline().process_many(msgs)
        assert [r.status for r in results] == [
            ResultStatus.PARSED,
            ResultStatus.DUPLICATE,
            ResultStatus.IGNORED,
        ]

    def test_summarize(self):
        rs = [ParseResult(ResultStatus.PARSED, "", ""), ParseResult(ResultStatus.IGNORED, "", "")]
        assert summarize(rs) == {"parsed": 1, "review": 0, "ignored": 1, "duplicate": 0}
