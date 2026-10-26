import json
from pathlib import Path

from hisaab.core.models import Direction
from hisaab.parsers import report
from hisaab.parsers.types import ParsedTxn

FIXTURES = Path(__file__).parent / "fixtures" / "sms"
EXP = {
    "direction": "debit",
    "amount_paise": 100,
    "account_tail": "1",
    "counterparty_name": None,
    "counterparty_vpa": None,
    "upi_ref": None,
    "txn_at": None,
}


def test_load_fixtures_skips_negatives():
    data = report.load_fixtures(FIXTURES)
    assert "negatives" not in data and "hdfc" in data


def test_score_message():
    ok = report.score_message(ParsedTxn(Direction.DEBIT, 100, "1"), EXP)
    assert all(ok.values())
    bad = report.score_message(None, EXP)
    assert bad["amount_paise"] is False and bad["txn_at"] is True


def test_evaluate_and_markdown():
    fixtures = {"x": [{"sender": "", "body": "b", "expected": EXP}]}
    scores = report.evaluate(fixtures, lambda s, b: ParsedTxn(Direction.DEBIT, 100, "9"))
    s = scores[0]
    assert s.parsed == 1 and s.correct["account_tail"] == 0
    assert abs(s.field_accuracy - 6 / 7) < 1e-9
    md = report.to_markdown(scores)
    assert "| x | 1 | 1 | 100% | 100% | 85.7% |" in md


def test_empty_scores():
    assert report.overall([]) == 1.0
    assert report.BankScore("x").field_accuracy == 1.0
    assert report.BankScore("x").accuracy("upi_ref") == 1.0


def test_real_corpus_meets_target():
    scores = report.evaluate(report.load_fixtures(FIXTURES), report.pipeline_parser())
    assert report.overall(scores) >= 0.95
    for s in scores:
        assert s.accuracy("amount_paise") == 1.0 and s.accuracy("direction") == 1.0


def test_main_exit_codes(tmp_path, capsys):
    assert report.main([str(FIXTURES)]) == 0
    assert "Overall field accuracy" in capsys.readouterr().out
    bad = {"bank": "bad", "messages": [{"sender": "", "body": "x", "expected": EXP}]}
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    assert report.main([str(tmp_path)]) == 1
