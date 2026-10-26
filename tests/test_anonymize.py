import re

from hisaab.parsers import generic
from hisaab.parsers.anonymize import FAKE_NAMES, Anonymizer
from hisaab.parsers.importers.sms_xml import parse_sms_xml

HDFC = "Sent Rs.450.00 from HDFC Bank A/c **1234 to RAHUL KUMAR on 24/10/26. Ref 429812345678."


def anon():
    return Anonymizer(salt="test")


class TestDigits:
    def test_deterministic_with_salt(self):
        assert anon()._digits("1234", 4) == anon()._digits("1234", 4)

    def test_length_and_no_leading_zero(self):
        for s in ["a", "b", "c", "d", "e", "f", "g"]:
            d = anon()._digits(s, 12)
            assert len(d) == 12 and d.isdigit() and d[0] != "0"

    def test_random_salt_by_default(self):
        assert Anonymizer().salt != Anonymizer().salt


class TestMasks:
    def test_accounts(self):
        out = anon().mask_accounts("A/c **1234 and Card XX9876 and Acct 1122334455")
        assert "1234" not in out and "9876" not in out and "1122334455" not in out
        assert re.search(r"A/c \*\*\d{4}", out)

    def test_vpas_keep_handle(self):
        out = anon().mask_vpas("to rahul.k@okaxis and rahul.k@okaxis")
        assert "rahul" not in out
        a, b = re.findall(r"user\d{4}@okaxis", out)
        assert a == b

    def test_mobiles(self):
        out = anon().mask_mobiles("call +91 9876543210 or 8123456789")
        assert "9876543210" not in out and "8123456789" not in out and "+91 9" in out

    def test_long_numbers_keep_helplines(self):
        out = anon().mask_long_numbers("Ref 429812345678 call 18002586161")
        assert "429812345678" not in out and "18002586161" in out
        assert re.search(r"Ref \d{12} ", out)

    def test_names(self):
        a = anon()
        out = a.mask_names(HDFC)
        assert "RAHUL KUMAR" not in out
        assert any(n in out for n in FAKE_NAMES)

    def test_fake_name_consistent_and_unique(self):
        a = anon()
        assert a.fake_name("RAHUL KUMAR") == a.fake_name("rahul  kumar".upper())
        names = {a.fake_name(f"PERSON{i} X") for i in range(len(FAKE_NAMES))}
        assert len(names) == len(FAKE_NAMES)
        assert a.fake_name("ONE MORE").startswith("PERSON")

    def test_fake_name_title_case(self):
        assert anon().fake_name("Rahul Kumar").istitle()


class TestAnonymizeText:
    def test_still_parses_after_masking(self):
        out = anon().anonymize_text(HDFC)
        for secret in ("1234", "RAHUL KUMAR", "429812345678"):
            assert secret not in out
        t = generic.parse(out)
        assert t.amount_paise == 45000 and t.upi_ref and len(t.upi_ref) == 12

    def test_same_ref_same_fake_across_messages(self):
        a = anon()
        x = a.anonymize_text("Ref 429812345678 debited Rs.5")
        y = a.anonymize_text("UPI Ref No 429812345678 paid Rs.5")
        assert re.search(r"\d{12}", x).group() == re.search(r"\d{12}", y).group()


def test_anonymize_xml(tmp_path):
    src = tmp_path / "in.xml"
    src.write_text(
        "<smses><sms address='AX-HDFCBK' type='1' date='1' body='" + HDFC + "' />"
        "<sms address='+919876543210' contact_name='Mom' type='1' body='hi' /></smses>",
        encoding="utf-8",
    )
    dest = tmp_path / "out.xml"
    assert anon().anonymize_xml(src, dest) == 2
    text = dest.read_text(encoding="utf-8")
    assert "RAHUL KUMAR" not in text and "9876543210" not in text and "Mom" not in text
    msgs = parse_sms_xml(dest)
    assert msgs[0].sender == "AX-HDFCBK"


def test_every_fixture_still_parses_after_anonymizing():
    """Contributors anonymize before sharing; formats must survive masking."""
    import importlib
    from pathlib import Path

    from hisaab.parsers.report import load_fixtures

    a = anon()
    corpus = load_fixtures(Path(__file__).parent / "fixtures" / "sms")
    for bank, msgs in corpus.items():
        mod = importlib.import_module(f"hisaab.parsers.banks.{bank}")
        for msg in msgs:
            masked = a.anonymize_text(msg["body"])
            txn = mod.parse(masked)
            assert txn is not None, masked
            assert txn.amount_paise == msg["expected"]["amount_paise"]
            assert txn.direction.value == msg["expected"]["direction"]
