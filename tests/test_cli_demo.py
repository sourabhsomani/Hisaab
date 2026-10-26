from datetime import date, datetime

import pytest
from sqlmodel import select

from hisaab import __main__ as cli
from hisaab.app import launch_kwargs
from hisaab.core import models as m
from hisaab.core.db import get_engine, init_db, session_scope
from hisaab.demo import demo_messages, repayment_sms, seed_demo
from hisaab.parsers.pipeline import default_pipeline
from hisaab.parsers.types import ResultStatus
from hisaab.services import groups as gsvc

END = date(2026, 10, 26)


class TestDemo:
    def test_messages_deterministic(self):
        assert demo_messages(seed=1, end=END) == demo_messages(seed=1, end=END)
        assert demo_messages(seed=1, end=END) != demo_messages(seed=2, end=END)

    def test_three_months_of_sms(self):
        msgs = demo_messages(end=END)
        dated = [x.received_at for x in msgs if x.received_at]
        assert (max(dated) - min(dated)).days >= 85
        assert sum("PRAKASH LANDLORD" in x.body for x in msgs) == 3

    def test_every_demo_sms_parses(self):
        pipe = default_pipeline()
        for msg in demo_messages(end=END):
            res = pipe.process(msg.sender, msg.body, msg.received_at)
            if "OTP" in msg.body:
                assert res.status is ResultStatus.IGNORED
            else:
                assert res.txn is not None and res.txn.bank in ("HDFC Bank", "ICICI Bank", "SBI")

    def test_repayment_sms_is_credit(self):
        msg = repayment_sms(datetime(2026, 10, 1), "ANANYA RAO", 4100)
        txn = default_pipeline().extract(msg.sender, msg.body)
        assert txn.direction is m.Direction.CREDIT and txn.amount_paise == 410000

    def test_seed_demo_full_loop(self):
        eng = get_engine(":memory:")
        init_db(eng)
        with session_scope(eng) as s:
            stats = seed_demo(s, end=END)
            assert stats["groups"] == 2 and stats["proposals"] == 1
            assert stats["transactions"] == stats["messages"] - 1  # the OTP is ignored
            (p,) = gsvc.list_settlements(s, status=m.SettlementStatus.PROPOSED)
            assert p.method == m.SettlementMethod.UPI_SMS
            assert len(s.exec(select(m.Group)).all()) == 2
            trip = gsvc.list_groups(s)[-1]
            assert all(ln.link for ln in gsvc.payment_lines(s, trip.id))
        eng.dispose()


class TestCli:
    def test_parser_defaults(self):
        args = cli.build_parser().parse_args([])
        assert args.command is None and args.host == "127.0.0.1" and args.port == 7860
        assert not args.demo

    def test_serve_flags(self):
        args = cli.build_parser().parse_args(["serve", "--demo", "--port", "9000"])
        assert args.command == "serve" and args.demo and args.port == 9000

    def test_version(self, capsys):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(["--version"])
        assert "hisaab 0.1.0" in capsys.readouterr().out

    def test_anonymize(self, tmp_path, capsys):
        src = tmp_path / "sms.xml"
        src.write_text(
            "<smses><sms address='AX-HDFCBK' type='1' body='Sent Rs.5 to RAHUL "
            "KUMAR from A/c XX1234 Ref 429812345678' /></smses>"
        )
        assert cli.main(["anonymize", str(src)]) == 0
        out = tmp_path / "sms.anonymized.xml"
        assert out.exists() and "429812345678" not in out.read_text()
        assert "Masked 1 SMS" in capsys.readouterr().out

    def test_anonymize_output_flag(self, tmp_path):
        src = tmp_path / "a.xml"
        src.write_text("<smses/>")
        assert cli.main(["anonymize", str(src), "-o", str(tmp_path / "b.xml")]) == 0
        assert (tmp_path / "b.xml").exists()

    def test_backup(self, tmp_path, capsys):
        db = tmp_path / "h.db"
        eng = get_engine(db)
        init_db(eng)
        eng.dispose()
        assert cli.main(["backup", str(tmp_path / "copy.db"), "--db", str(db)]) == 0
        assert (tmp_path / "copy.db").exists() and "Backup written" in capsys.readouterr().out

    def test_serve_dispatch(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(cli, "cmd_serve", lambda a: seen.setdefault("args", a) and 0)
        cli.main(["--demo"])
        assert seen["args"].demo


def test_demo_may_bind_publicly_without_password():
    assert launch_kwargs("0.0.0.0", demo=True)["server_name"] == "0.0.0.0"
