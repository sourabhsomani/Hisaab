"""Fixture tests: every anonymized SMS has expected output; amount and direction must be exact."""

import importlib
import json
import re
from pathlib import Path

import pytest

from hisaab.core.models import Direction
from hisaab.parsers.banks import _base, discover
from hisaab.parsers.pipeline import Pipeline, default_pipeline
from hisaab.parsers.report import FIELDS, load_fixtures
from hisaab.parsers.types import ResultStatus

FIXTURES = Path(__file__).parent / "fixtures" / "sms"
CORPUS = load_fixtures(FIXTURES)
CASES = [(bank, i, msg) for bank, msgs in CORPUS.items() for i, msg in enumerate(msgs)]
NEGATIVES = json.loads((FIXTURES / "negatives.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("bank,i,msg", CASES, ids=[f"{b}-{i}" for b, i, _ in CASES])
def test_bank_plugin_matches_expected(bank, i, msg):
    module = importlib.import_module(f"hisaab.parsers.banks.{bank}")
    txn = module.parse(msg["body"])
    assert txn is not None, "bank plugin did not match"
    got = txn.as_dict()
    for field in FIELDS:
        assert got[field] == msg["expected"][field], field
    assert txn.bank == module.BANK


@pytest.mark.parametrize("bank,i,msg", CASES, ids=[f"{b}-{i}" for b, i, _ in CASES])
def test_pipeline_keeps_every_fixture(bank, i, msg):
    res = default_pipeline().process(msg["sender"], msg["body"])
    assert res.status in (ResultStatus.PARSED, ResultStatus.REVIEW)
    assert res.txn.amount_paise == msg["expected"]["amount_paise"]
    assert res.txn.direction.value == msg["expected"]["direction"]


@pytest.mark.parametrize("neg", NEGATIVES, ids=[n["reason"] for n in NEGATIVES])
def test_negative_fixtures_never_become_transactions(neg):
    res = default_pipeline().process(neg["sender"], neg["body"])
    assert res.status is ResultStatus.IGNORED
    assert res.reason == neg["reason"]


def test_every_bank_has_fixtures():
    names = {m.__name__.rsplit(".", 1)[1] for m in discover()}
    assert names == set(CORPUS)


def test_plugins_do_not_claim_other_banks():
    """A plugin must return None for SMS of every other bank (no cross-bank false positives)."""
    for mod in discover():
        own = mod.__name__.rsplit(".", 1)[1]
        for bank, msgs in CORPUS.items():
            if bank == own:
                continue
            for msg in msgs:
                assert mod.parse(msg["body"]) is None, f"{own} matched {bank}: {msg['body']}"


class TestDiscover:
    def test_finds_top_banks(self):
        names = {m.__name__.rsplit(".", 1)[1] for m in discover()}
        assert {"hdfc", "sbi", "icici", "axis", "kotak", "pnb", "bob", "canara"} <= names

    def test_skips_private_modules(self):
        assert all(not m.__name__.rsplit(".", 1)[1].startswith("_") for m in discover())

    def test_plugin_contract(self):
        for m in discover():
            assert isinstance(m.SENDERS, list) and m.SENDERS
            assert isinstance(m.BANK, str)
            assert callable(m.parse)


def test_default_pipeline_has_banks():
    assert len(default_pipeline().banks) == len(discover())
    assert isinstance(default_pipeline(), Pipeline)


class TestBase:
    def test_P_is_case_insensitive(self):
        assert _base.P(r"debited").regex.search("DEBITED")

    def test_direction_from_word(self):
        assert _base.direction_from_word("DEBITED") is Direction.DEBIT
        assert _base.direction_from_word("Credit") is Direction.CREDIT
        assert _base.direction_from_word(None) is None

    def test_build_moves_vpa_out_of_name(self):
        m = re.search(r"(?P<amount>\d+) to (?P<name>\S+)", "50 to amit@ybl")
        t = _base.build("50 to amit@ybl", m, "X", Direction.DEBIT)
        assert t.counterparty_vpa == "amit@ybl" and t.counterparty_name is None

    def test_build_needs_direction(self):
        m = re.search(r"(?P<amount>\d+)", "50")
        assert _base.build("50", m, "X", None) is None

    def test_build_bad_amount(self):
        m = re.search(r"(?P<amount>[a-z]+)", "abc")
        assert _base.build("abc", m, "X", Direction.DEBIT) is None

    def test_build_fills_from_body(self):
        body = "50 paid. UPI Ref No 123456789012 on 01/02/26 from A/c XX4321"
        m = re.search(r"(?P<amount>\d+) paid", body)
        t = _base.build(body, m, "X", Direction.DEBIT)
        assert (t.upi_ref, t.account_tail, t.txn_at.month) == ("123456789012", "4321", 2)
        assert t.confidence == _base.BANK_CONFIDENCE

    def test_match_first_none(self):
        assert _base.match_first("nothing", [_base.P(r"(?P<amount>\d+) debited")], "X") is None

    def test_match_first_skips_unbuildable(self):
        pats = [_base.P(r"(?P<amount>\d+)"), _base.P(r"(?P<amount>\d+)", Direction.CREDIT)]
        assert _base.match_first("50", pats, "X").direction is Direction.CREDIT
