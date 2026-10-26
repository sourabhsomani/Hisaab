import json

import pytest

from hisaab.core.models import Direction
from hisaab.parsers import llm
from hisaab.parsers.categorize import Categorizer
from hisaab.parsers.pipeline import Pipeline
from hisaab.parsers.types import ParsedTxn, ResultStatus

CFG = llm.LLMConfig()


def reply(content):
    calls = []

    def transport(url, payload, timeout):
        calls.append((url, payload, timeout))
        text = content if isinstance(content, str) else json.dumps(content)
        return {"choices": [{"message": {"content": text}}]}

    transport.calls = calls
    return transport


class TestLocalOnly:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:11434/v1",
            "http://localhost:1/v1",
            "http://[::1]:11434",
            "http://ollama.localhost/v1",
        ],
    )
    def test_local(self, url):
        assert llm.is_local_url(url)

    def test_remote(self):
        assert not llm.is_local_url("https://api.example.com/v1")

    def test_chat_refuses_remote(self):
        with pytest.raises(PermissionError):
            llm.chat(llm.LLMConfig(base_url="https://api.example.com/v1"), "s", "u", reply("x"))

    def test_chat_remote_allowed_explicitly(self):
        cfg = llm.LLMConfig(base_url="https://api.example.com/v1/", allow_remote=True)
        t = reply("ok")
        assert llm.chat(cfg, "s", "u", t) == "ok"
        assert t.calls[0][0] == "https://api.example.com/v1/chat/completions"


def test_chat_payload():
    t = reply("hi")
    assert llm.chat(CFG, "sys", "usr", t) == "hi"
    url, payload, timeout = t.calls[0]
    assert payload["model"] == "llama3.2" and payload["temperature"] == 0
    assert payload["messages"][1] == {"role": "user", "content": "usr"}
    assert timeout == 20.0


class TestExtractJson:
    def test_fenced(self):
        assert llm.extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}

    def test_skips_invalid(self):
        assert llm.extract_json('{oops} then {"b": 2}') == {"b": 2}

    def test_none(self):
        assert llm.extract_json("no json") is None


class TestCategorizer:
    def test_valid_category_capped(self):
        cat = llm.make_categorizer(CFG, reply({"category": "Food", "confidence": 0.99}))
        assert cat(ParsedTxn(Direction.DEBIT, 1, merchant="X"), ["Food"]) == ("Food", 0.75)

    def test_unknown_category_rejected(self):
        cat = llm.make_categorizer(CFG, reply({"category": "Crypto"}))
        assert cat(ParsedTxn(Direction.DEBIT, 1), ["Food"]) == (None, 0.0)

    def test_bad_confidence_defaults(self):
        cat = llm.make_categorizer(CFG, reply({"category": "Food", "confidence": "high"}))
        assert cat(ParsedTxn(Direction.DEBIT, 1), ["Food"]) == ("Food", 0.5)

    def test_plugs_into_categorizer(self):
        c = Categorizer(
            llm=llm.make_categorizer(CFG, reply({"category": "Bills", "confidence": 0.7})),
            categories=["Bills"],
        )
        assert c.categorize(ParsedTxn(Direction.DEBIT, 1, merchant="Q 9")) == ("Bills", 0.7)


class TestExtractor:
    def test_extracts(self):
        ex = llm.make_extractor(
            CFG,
            reply(
                {
                    "direction": "debit",
                    "amount": 450.5,
                    "account_tail": "XX1234",
                    "counterparty": "RAHUL",
                    "upi_ref": 429812345678,
                }
            ),
        )
        t = ex("weird sms")
        assert (t.direction, t.amount_paise, t.account_tail, t.upi_ref, t.confidence) == (
            Direction.DEBIT,
            45050,
            "1234",
            "429812345678",
            llm.LLM_EXTRACT_CONFIDENCE,
        )

    @pytest.mark.parametrize(
        "obj",
        [
            {"direction": None},
            {"direction": "debit"},
            {"direction": "debit", "amount": 0},
            {"direction": "sideways", "amount": 5},
        ],
    )
    def test_rejects(self, obj):
        assert llm.make_extractor(CFG, reply(obj))("x") is None

    def test_pipeline_review_for_llm_results(self):
        ex = llm.make_extractor(CFG, reply({"direction": "debit", "amount": 20}))
        r = Pipeline(llm_extract=ex).process("", "money debited somewhere mysterious")
        assert r.txn.bank == "llm" and r.status is ResultStatus.REVIEW
