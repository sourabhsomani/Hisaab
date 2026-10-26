from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from defusedxml.common import EntitiesForbidden

from hisaab.core.models import Direction
from hisaab.parsers.importers import statement_csv as st
from hisaab.parsers.importers import whatsapp as wa
from hisaab.parsers.importers.sms_xml import epoch_ms_to_local, parse_sms_xml, split_pasted

FILES = Path(__file__).parent / "fixtures" / "files"
XML = (FILES / "sms_backup.xml").read_text(encoding="utf-8")


class TestSmsXml:
    def test_epoch_to_ist(self):
        # 2024-10-24 14:30:00 UTC -> 20:00 IST
        assert epoch_ms_to_local(1729780200000) == datetime(2024, 10, 24, 20, 0)

    def test_keeps_inbox_bank_sms(self):
        msgs = parse_sms_xml(XML)
        assert [m.sender for m in msgs] == ["AX-HDFCBK", "JD-SBIUPI"]
        assert msgs[0].received_at == datetime(2024, 10, 24, 20, 0)
        assert msgs[1].received_at is None

    def test_all_senders(self):
        assert len(parse_sms_xml(XML, banks_only=False)) == 3

    def test_from_path_and_bytes(self, tmp_path):
        p = tmp_path / "sms.xml"
        p.write_text(XML, encoding="utf-8")
        assert (
            len(parse_sms_xml(p)) == len(parse_sms_xml(str(p))) == len(parse_sms_xml(XML.encode()))
        )

    def test_blocks_entity_bomb(self):
        bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><smses>&a;</smses>'
        with pytest.raises(EntitiesForbidden):
            parse_sms_xml(bomb)


class TestSplitPasted:
    def test_blocks_and_sender_header(self):
        text = "AX-HDFCBK:\nSent Rs.5 to X\n\nRs.10 debited\nfrom A/c 1234\n\n\n"
        msgs = split_pasted(text)
        assert msgs[0].sender == "AX-HDFCBK" and msgs[0].body == "Sent Rs.5 to X"
        assert msgs[1].sender == "" and msgs[1].body == "Rs.10 debited from A/c 1234"

    def test_windows_newlines(self):
        assert len(split_pasted("a debited\r\n\r\nb credited")) == 2

    def test_empty(self):
        assert split_pasted("  \n\n ") == []


HDFC_CSV = (FILES / "hdfc_statement.csv").read_text(encoding="utf-8")


class TestStatement:
    def test_detect_columns_hdfc(self):
        cols = st.detect_columns(
            ["Date", "Narration", "Chq./Ref.No.", "Withdrawal Amt.", "Deposit Amt."]
        )
        assert cols == st.Columns(
            date="Date",
            description="Narration",
            debit="Withdrawal Amt.",
            credit="Deposit Amt.",
            ref="Chq./Ref.No.",
        )

    def test_detect_columns_amount_type(self):
        cols = st.detect_columns(["Transaction Date", "Description", "Amount", "Dr/Cr"])
        assert cols.amount == "Amount" and cols.type == "Dr/Cr"

    @pytest.mark.parametrize("headers", [["Date", "Amount"], ["Date", "Narration", "Balance"]])
    def test_detect_columns_errors(self, headers):
        with pytest.raises(ValueError):
            st.detect_columns(headers)

    def test_find_header_row(self):
        frame = pd.DataFrame([["Bank"], ["x"], ["Date"]])
        with pytest.raises(ValueError):
            st.find_header_row(frame)

    def test_parse_narration_hdfc(self):
        assert st.parse_narration(
            "UPI-RAHUL KUMAR-rahul@okaxis-HDFC0001234-429812345678-PAYMENT"
        ) == ("RAHUL KUMAR", "rahul@okaxis", "429812345678")

    def test_parse_narration_slash(self):
        assert st.parse_narration("UPI/P2A/429812345678/PRIYA SHARMA/priya@ybl") == (
            "PRIYA SHARMA",
            "priya@ybl",
            "429812345678",
        )

    def test_parse_narration_non_upi(self):
        assert st.parse_narration("POS 4455 AMAZON") == (None, None, None)

    def test_import_csv(self, tmp_path):
        p = tmp_path / "stmt.csv"
        p.write_text(HDFC_CSV, encoding="utf-8")
        txns = st.import_statement(p)
        assert len(txns) == 3
        a, b, c = txns
        assert (a.direction, a.amount_paise, a.counterparty_name, a.upi_ref) == (
            Direction.DEBIT,
            45000,
            "RAHUL KUMAR",
            "429812345678",
        )
        assert a.txn_at == datetime(2026, 10, 24)
        assert (b.direction, b.amount_paise, b.counterparty_vpa) == (
            Direction.CREDIT,
            120000,
            "priya@ybl",
        )
        assert c.merchant == "POS 4455 AMAZON PAY INDIA" and c.upi_ref is None
        assert all(t.confidence == st.STATEMENT_CONFIDENCE for t in txns)

    def test_import_excel_amount_type(self, tmp_path):
        p = tmp_path / "stmt.xlsx"
        pd.DataFrame(
            [
                ["Account statement", None, None, None],
                ["Transaction Date", "Description", "Amount", "Dr/Cr"],
                ["01-11-2026", "UPI/429800001111/AMIT VERMA/amit@ybl", "300", "DR"],
                ["02-11-2026", "Salary", "50,000.00", "CR"],
                ["03-11-2026", "nothing", "", "DR"],
            ]
        ).to_excel(p, header=False, index=False)
        txns = st.import_statement(p)
        assert [(t.direction, t.amount_paise) for t in txns] == [
            (Direction.DEBIT, 30000),
            (Direction.CREDIT, 5000000),
        ]

    @pytest.mark.parametrize(
        "v,expected",
        [(None, 0), (float("nan"), 0), ("-", 0), ("x", 0), ("1,200.50", 120050), ("-450", 45000)],
    )
    def test_amount(self, v, expected):
        assert st._amount(v) == expected

    def test_row_without_amount(self):
        cols = st.Columns(date="d", description="n", debit="w", credit="c")
        assert st.row_to_txn(pd.Series({"d": "1/1/26", "n": "x", "w": "", "c": ""}), cols) is None


CHAT = """24/10/26, 9:15 pm - Rahul: paid 1200 for the cab
24/10/26, 9:16 pm - Priya: ok
24/10/26, 9:20 pm - Priya: ₹600 dinner at Fisherman's Wharf
[25/10/26, 10:01:03 AM] Amit: maine 500 diye petrol ke liye
25/10/26, 10:05 am - Amit: <Media omitted>
25/10/26, 11:00 am - Rahul: spent Rs.2,450.50 on
groceries for the flat
"""


class TestWhatsapp:
    def test_parse_lines_joins_continuations(self):
        lines = wa.parse_lines(CHAT)
        assert len(lines) == 6
        assert lines[-1].text == "spent Rs.2,450.50 on groceries for the flat"
        assert lines[0].at == datetime(2026, 10, 24, 21, 15)
        assert lines[3].author == "Amit" and lines[3].at == datetime(2026, 10, 25, 10, 1, 3)

    def test_parse_chat(self):
        out = wa.parse_chat(CHAT)
        assert [(e.payer, e.amount_paise, e.description) for e in out] == [
            ("Rahul", 120000, "Cab"),
            ("Priya", 60000, "Dinner at fisherman's wharf"),
            ("Amit", 50000, "Petrol"),
            ("Rahul", 245050, "Groceries flat"),
        ]

    def test_extract_ignores_chatter(self):
        assert wa.extract_expense(wa.ChatLine(None, "A", "kal milte hain")) is None
        assert wa.extract_expense(wa.ChatLine(None, "A", "<Media omitted>")) is None
        assert wa.extract_expense(wa.ChatLine(None, "A", "paid 0 for nothing")) is None

    def test_clean_description(self):
        assert wa.clean_description("the cab!!") == "Cab"
        assert wa.clean_description("") == "Expense"
