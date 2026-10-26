import pytest

from hisaab.core.models import Direction
from hisaab.parsers.categorize import (
    KEYWORD_CONFIDENCE,
    PERSON_CONFIDENCE,
    RULE_CONFIDENCE,
    Categorizer,
    CategoryRule,
    looks_like_person,
)
from hisaab.parsers.types import ParsedTxn


def debit(**kw):
    return ParsedTxn(Direction.DEBIT, 100, **kw)


class TestRule:
    def test_matches_case_insensitive(self):
        assert CategoryRule("merchant", "tea stall", "Food").matches(
            debit(merchant="Sharma TEA STALL")
        )

    def test_regex_chars_are_literal(self):
        assert not CategoryRule("merchant", "a.c", "X").matches(debit(merchant="abc"))

    def test_missing_field(self):
        assert not CategoryRule("merchant", "x", "X").matches(debit())


@pytest.mark.parametrize(
    "name,expected",
    [
        ("RAHUL KUMAR", True),
        ("Priya", True),
        ("A. B. Sharma", False),
        ("SHARMA STORE", False),
        ("Shop 42", False),
        (None, False),
    ],
)
def test_looks_like_person(name, expected):
    assert looks_like_person(name) is expected


class TestCategorizer:
    def test_rule_beats_keyword(self):
        c = Categorizer(rules=[CategoryRule("merchant", "swiggy", "Office")])
        assert c.categorize(debit(merchant="Swiggy")) == ("Office", RULE_CONFIDENCE)

    def test_known_merchant(self):
        assert Categorizer().categorize(debit(merchant="Swiggy")) == ("Food", KEYWORD_CONFIDENCE)

    def test_keyword_in_vpa(self):
        assert Categorizer().categorize(debit(counterparty_vpa="irctc@sbi")) == (
            "Travel",
            KEYWORD_CONFIDENCE,
        )

    def test_person_is_transfer(self):
        assert Categorizer().categorize(debit(counterparty_name="RAHUL KUMAR")) == (
            "Transfers",
            PERSON_CONFIDENCE,
        )

    def test_credit_is_transfer(self):
        t = ParsedTxn(Direction.CREDIT, 100)
        assert Categorizer().categorize(t) == ("Transfers", PERSON_CONFIDENCE)

    def test_unknown_without_llm(self):
        assert Categorizer().categorize(debit(merchant="Xyz 123")) == (None, 0.0)

    def test_llm_fallback(self):
        seen = {}

        def llm(txn, cats):
            seen["cats"] = cats
            return "Shopping", 0.72

        c = Categorizer(llm=llm, categories=["Food", "Shopping"])
        assert c.categorize(debit(merchant="Xyz 123")) == ("Shopping", 0.72)
        assert seen["cats"] == ["Food", "Shopping"]

    def test_llm_errors_are_swallowed(self):
        def boom(txn, cats):
            raise ConnectionError("ollama down")

        assert Categorizer(llm=boom).categorize(debit(merchant="Xyz 1")) == (None, 0.0)

    def test_llm_none_answer(self):
        assert Categorizer(llm=lambda t, c: (None, 0.9)).categorize(debit(merchant="Q 1")) == (
            None,
            0.0,
        )
