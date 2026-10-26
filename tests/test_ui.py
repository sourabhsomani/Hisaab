"""UI handler tests (no browser) plus a smoke test that every tab builds."""

from pathlib import Path

import gradio as gr
import pandas as pd
import pytest
from PIL.Image import Image

from hisaab.app import TABS, build_app, launch_kwargs, make_ctx
from hisaab.core.models import Direction
from hisaab.parsers.types import ParsedTxn
from hisaab.services import groups as gsvc
from hisaab.services.importing import add_manual_txn
from hisaab.ui import common as c
from hisaab.ui import groups_tab, import_tab, inbox_tab, insights_tab, settings_tab, settle_tab

FILES = Path(__file__).parent / "fixtures" / "files"
HDFC = (
    "AX-HDFCBK:\nSent Rs.450.00 from HDFC Bank A/c **1234 to RAHUL KUMAR on 24/10/26. "
    "Ref 429812345678."
)
CREDIT = (
    "VM-ICICIT:\nDear Customer, Acct XX321 is credited with Rs 300.00 on 25-Oct-26 from RAHUL "
    "KUMAR. UPI:529987654321-ICICI Bank."
)


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path / "h.db")


@pytest.fixture
def trip(ctx):
    msg, upd = groups_tab.handle_create_group(ctx, "Goa", "trip", "Me")
    gid = upd["value"]
    groups_tab.handle_add_member(ctx, gid, "Rahul Kumar", "rahul@okaxis", "")
    groups_tab.handle_add_member(ctx, gid, "Priya", "", "")
    ids = [mid for _, mid in c.member_choices(ctx, gid)]
    return gid, ids


class TestCommon:
    def test_ctx_settings_saved(self, ctx):
        s = ctx.settings
        s.llm_model = "qwen"
        ctx.save(s)
        assert ctx.settings_file.exists()

    def test_demo_ctx_never_writes(self, tmp_path):
        demo = make_ctx(tmp_path / "x.db", demo=True)
        demo.save(demo.settings)
        assert not (tmp_path / "settings.json").exists()

    def test_make_pipeline_respects_settings(self, ctx):
        st = ctx.settings
        st.disabled_banks = ["hdfc"]
        st.llm_enabled = True
        with ctx.session() as s:
            pipe = c.make_pipeline(s, st)
        assert "hisaab.parsers.banks.hdfc" not in [b.__name__ for b in pipe.banks]
        assert pipe.llm_extract is not None and pipe.categorizer.llm is not None

    def test_messages(self):
        assert c.ok("x").startswith("✅") and c.err("x").startswith("⚠️")
        assert c.rupees(None) == "" and c.rupees(12345) == "₹123.45"

    @pytest.mark.parametrize("bad", [None, "", "  ", "0", "abc"])
    def test_amount_input_errors(self, bad):
        with pytest.raises(ValueError):
            c.amount_input(bad)

    def test_amount_input(self):
        assert c.amount_input("₹1,200.50") == 120050 and c.amount_input(5) == 500

    def test_parse_values_named_and_positional(self):
        names = {1: "Me (me)", 2: "Rahul Kumar"}
        assert c.parse_values("me=2, rahul=1", [1, 2], names) == {1: "2", 2: "1"}
        assert c.parse_values("2; 1", [1, 2], names) == {1: "2", 2: "1"}
        assert c.parse_values("", [1, 2], names) == {}
        with pytest.raises(ValueError, match="not a participant"):
            c.parse_values("zed=1", [1, 2], names)
        with pytest.raises(ValueError, match="expected 2"):
            c.parse_values("1", [1, 2], names)

    def test_values_for(self):
        assert c.values_for("exact", {1: "700", 2: "₹5.50"}) == {1: 70000, 2: 550}
        assert c.values_for("adjustment", {1: "-50"}) == {1: -5000}
        assert c.values_for("shares", {1: "2"}) == {1: 2.0}

    def test_choices_empty(self, ctx):
        assert c.group_choices(ctx) == [] and c.member_choices(ctx, None) == []


class TestImportTab:
    def test_paste(self, ctx):
        assert "1 transactions" in import_tab.handle_paste(ctx, HDFC)
        assert import_tab.handle_paste(ctx, "  ").startswith("⚠️")

    def test_paste_finds_repayment(self, ctx, trip):
        gid, (me, rahul, priya) = trip
        groups_tab.handle_add_expense(ctx, gid, "Cab", "900", me, [me, rahul, priya], "equal", "")
        out = import_tab.handle_paste(ctx, CREDIT)
        assert "Possible repayment" in out and "₹300.00" in out

    def test_paste_delete_raw(self, ctx):
        ctx.settings.delete_raw_sms = True
        import_tab.handle_paste(ctx, HDFC)
        with ctx.session() as s:
            from sqlmodel import select

            from hisaab.core.models import RawMessage

            assert s.exec(select(RawMessage)).one().body is None

    def test_upload_xml_and_csv(self, ctx):
        assert "transactions" in import_tab.handle_upload(ctx, str(FILES / "sms_backup.xml"))
        assert "transactions" in import_tab.handle_upload(ctx, str(FILES / "hdfc_statement.csv"))

    def test_upload_errors(self, ctx, tmp_path):
        assert import_tab.handle_upload(ctx, None).startswith("⚠️")
        bad = tmp_path / "x.pdf"
        bad.write_text("x")
        assert "Unsupported" in import_tab.handle_upload(ctx, str(bad))
        broken = tmp_path / "x.xml"
        broken.write_text("<not closed")
        assert "Could not read" in import_tab.handle_upload(ctx, str(broken))

    def test_whatsapp_flow(self, ctx, trip, tmp_path):
        gid, _ = trip
        chat = tmp_path / "chat.txt"
        chat.write_text(
            "24/10/26, 9:15 pm - Rahul Kumar: paid 1200 for the cab\n"
            "24/10/26, 9:20 pm - Stranger: paid 50 for chai\n",
            encoding="utf-8",
        )
        df, note = import_tab.whatsapp_preview(str(chat))
        assert len(df) == 2 and note.startswith("✅")
        out = import_tab.whatsapp_add(ctx, gid, df)
        assert "Added 1" in out and "Stranger" in out
        with ctx.session() as s:
            assert gsvc.list_expenses(s, gid)[0].total_paise == 120000

    def test_whatsapp_edge_cases(self, ctx, tmp_path):
        assert import_tab.whatsapp_preview(None)[1].startswith("⚠️")
        empty = tmp_path / "e.txt"
        empty.write_text("nothing here")
        assert import_tab.whatsapp_preview(str(empty))[1].startswith("⚠️")
        assert import_tab.whatsapp_add(ctx, None, None).startswith("⚠️")
        assert import_tab.whatsapp_add(ctx, 1, pd.DataFrame()).startswith("⚠️")

    def test_match_member(self):
        members = [("Me (me)", 1), ("Rahul Kumar", 2)]
        assert import_tab.match_member("Rahul", members) == 2
        assert import_tab.match_member("me", members) == 1
        assert import_tab.match_member("Zed", members) is None


class TestInboxTab:
    def test_tables_and_category(self, ctx):
        import_tab.handle_paste(ctx, "Rs.99 debited at XYZ 123")
        df = inbox_tab.inbox_table(ctx)
        assert list(df.columns) == inbox_tab.COLUMNS and len(df) == 1
        tid = int(df.iloc[0]["id"])
        msg, df2 = inbox_tab.handle_category(ctx, tid, "Shopping", True, False)
        assert "Shopping" in msg and df2.empty
        assert len(inbox_tab.inbox_table(ctx, show_all=True)) == 1

    def test_category_errors(self, ctx):
        assert inbox_tab.handle_category(ctx, 1, None, False, False)[0].startswith("⚠️")
        assert inbox_tab.handle_category(ctx, None, "Food", False, False)[0].startswith("⚠️")
        assert inbox_tab.handle_category(ctx, 99, "Food", False, False)[0].startswith("⚠️")

    def test_confirm(self, ctx):
        import_tab.handle_paste(ctx, "Rs.99 debited at XYZ 123")
        tid = int(inbox_tab.inbox_table(ctx).iloc[0]["id"])
        assert inbox_tab.handle_confirm(ctx, tid, True)[0].startswith("✅")
        assert inbox_tab.handle_confirm(ctx, 999, True)[0].startswith("⚠️")

    def test_split(self, ctx, trip):
        gid, (me, rahul, priya) = trip
        with ctx.session() as s:
            t = add_manual_txn(s, ParsedTxn(Direction.DEBIT, 90000, merchant="Swiggy"))
        msg, _ = inbox_tab.handle_split(ctx, t.id, gid, [me, rahul], "shares", "2, 1", True)
        assert "Split ₹900.00 in Goa" in msg
        assert inbox_tab.handle_split(ctx, t.id, gid, [me], "equal", "", True)[0].startswith("⚠️")
        assert inbox_tab.handle_split(ctx, t.id, None, [me], "equal", "", 1)[0].startswith("⚠️")
        assert inbox_tab.handle_split(ctx, t.id, gid, [], "equal", "", 1)[0].startswith("⚠️")

    def test_unparsed_text(self, ctx):
        assert inbox_tab.unparsed_text(ctx) == ""
        import_tab.handle_paste(ctx, "Your a/c was debited today")
        assert "could not be read" in inbox_tab.unparsed_text(ctx)

    def test_pick_row(self):
        df = pd.DataFrame({"id": [5, 7]})
        evt = type("E", (), {"index": [1, 0]})()
        assert inbox_tab.pick_row(df, evt) == 7


class TestGroupsTab:
    def test_tables(self, ctx, trip):
        gid, (me, rahul, priya) = trip
        assert groups_tab.members_table(ctx, gid)["name"].tolist() == [
            "Me (me)",
            "Rahul Kumar",
            "Priya",
        ]
        assert groups_tab.members_table(ctx, None).empty
        assert groups_tab.expenses_table(ctx, None).empty

    def test_create_group_error(self, ctx):
        msg, _ = groups_tab.handle_create_group(ctx, "", "trip", "Me")
        assert msg.startswith("⚠️")

    def test_create_group_with_upi(self, ctx):
        msg, upd = groups_tab.handle_create_group(ctx, "Flat", "flat", "Me", "me@okicici")
        assert msg.startswith("✅")
        assert groups_tab.members_table(ctx, upd["value"]).iloc[0]["UPI ID"] == "me@okicici"

    def test_update_member(self, ctx, trip):
        gid, (me, rahul, priya) = trip
        msg, df = groups_tab.handle_update_member(ctx, gid, me, "me@okicici", "SOURABH S")
        assert msg.startswith("✅") and df.iloc[0]["UPI ID"] == "me@okicici"
        assert groups_tab.handle_update_member(ctx, gid, None, "", "")[0].startswith("⚠️")
        assert groups_tab.handle_update_member(ctx, gid, me, "bad", "")[0].startswith("⚠️")

    def test_add_member_errors(self, ctx, trip):
        gid, _ = trip
        assert groups_tab.handle_add_member(ctx, None, "x", "", "")[0].startswith("⚠️")
        assert groups_tab.handle_add_member(ctx, gid, "x", "bad", "")[0].startswith("⚠️")

    def test_expenses(self, ctx, trip):
        gid, (me, rahul, priya) = trip
        msg, df = groups_tab.handle_add_expense(
            ctx, gid, "Villa", "1,200", rahul, [me, rahul], "exact", "Me=700, Rahul=500"
        )
        assert msg == "✅ Added ₹1,200.00 · Villa." and df.iloc[0]["paid by"] == "Rahul Kumar"
        eid = int(df.iloc[0]["id"])
        assert groups_tab.handle_delete_expense(ctx, gid, eid)[1].empty
        assert groups_tab.handle_delete_expense(ctx, gid, None)[0].startswith("⚠️")

    @pytest.mark.parametrize(
        "args",
        [
            (None, "x", "1", 1, [1], "equal", ""),
            ("G", "x", "1", None, [1], "equal", ""),
            ("G", "x", "1", 1, [], "equal", ""),
            ("G", "x", "", 1, [1], "equal", ""),
        ],
    )
    def test_expense_errors(self, ctx, trip, args):
        gid, (me, *_) = trip
        args = tuple(gid if a == "G" else (me if a == 1 else a) for a in args[:4]) + args[4:]
        assert groups_tab.handle_add_expense(ctx, *args)[0].startswith("⚠️")


class TestSettleTab:
    def test_tables_qr_summary(self, ctx, trip):
        gid, (me, rahul, priya) = trip
        groups_tab.handle_add_expense(
            ctx, gid, "Cab", "900", rahul, [me, rahul, priya], "equal", ""
        )
        bal = settle_tab.balances_table(ctx, gid)
        assert set(bal["status"]) == {"owes", "gets back"}
        plan = settle_tab.plan_table(ctx, gid)
        assert len(plan) == 2 and plan.iloc[0]["UPI link"].startswith("upi://pay")
        assert isinstance(settle_tab.qr_for(ctx, gid, 1), Image)
        assert settle_tab.qr_for(ctx, gid, 9) is None and settle_tab.qr_for(ctx, None, 1) is None
        assert "Goa" in settle_tab.summary_text(ctx, gid)

    def test_empty_group_views(self, ctx):
        assert settle_tab.balances_table(ctx, None).empty
        assert settle_tab.plan_table(ctx, None).empty
        assert settle_tab.summary_text(ctx, None) == ""

    def test_qr_none_without_vpa(self, ctx, trip):
        gid, (me, rahul, priya) = trip
        groups_tab.handle_add_expense(ctx, gid, "x", "10", priya, [me, priya], "equal", "")
        assert settle_tab.qr_for(ctx, gid, 1) is None

    def test_proposals(self, ctx, trip):
        gid, (me, rahul, priya) = trip
        groups_tab.handle_add_expense(ctx, gid, "Cab", "900", me, [me, rahul, priya], "equal", "")
        import_tab.handle_paste(ctx, CREDIT)
        props = settle_tab.proposals_table(ctx)
        assert props.iloc[0]["from"] == "Rahul Kumar" and props.iloc[0]["amount"] == "₹300.00"
        msg, after = settle_tab.handle_proposal(ctx, int(props.iloc[0]["id"]), True)
        assert msg.startswith("✅") and after.empty
        assert settle_tab.handle_proposal(ctx, None, False)[0].startswith("⚠️")

    def test_reject_proposal(self, ctx, trip):
        gid, (me, rahul, priya) = trip
        groups_tab.handle_add_expense(ctx, gid, "Cab", "900", me, [me, rahul, priya], "equal", "")
        import_tab.handle_paste(ctx, CREDIT)
        pid = int(settle_tab.proposals_table(ctx).iloc[0]["id"])
        assert settle_tab.handle_proposal(ctx, pid, False)[0] == "✅ Dismissed."

    def test_manual(self, ctx, trip):
        gid, (me, rahul, priya) = trip
        assert settle_tab.handle_manual(ctx, gid, rahul, me, "100").startswith("✅")
        assert settle_tab.handle_manual(ctx, None, rahul, me, "100").startswith("⚠️")
        assert settle_tab.handle_manual(ctx, gid, me, me, "100").startswith("⚠️")


class TestInsightsTab:
    def test_data(self, ctx):
        from datetime import datetime

        with ctx.session() as s:
            add_manual_txn(
                s,
                ParsedTxn(Direction.DEBIT, 25000, merchant="Swiggy", txn_at=datetime(2026, 10, 1)),
                "Food",
            )
        ctx.settings.budgets = {"Food": 10000}
        headline, monthly, cats, merchants, budgets = insights_tab.insights_data(ctx, None)
        assert "₹250.00 spent in 2026-10" in headline and "Over budget: Food" in headline
        assert budgets.iloc[0]["left"] == "-₹150.00" and budgets.iloc[0]["used"] == "250%"
        assert insights_tab.months(ctx) == ["2026-10"]

    def test_empty(self, ctx):
        headline, *_ = insights_tab.insights_data(ctx, None)
        assert "₹0.00 spent" in headline


class TestSettingsTab:
    def test_rules(self, ctx):
        import_tab.handle_paste(ctx, "Rs.99 debited at XYZ 123")
        tid = int(inbox_tab.inbox_table(ctx).iloc[0]["id"])
        inbox_tab.handle_category(ctx, tid, "Shopping", True, False)
        rules = settings_tab.rules_table(ctx)
        assert rules.iloc[0]["contains"] == "Xyz 123"
        msg, after = settings_tab.handle_delete_rule(ctx, int(rules.iloc[0]["id"]))
        assert after.empty
        assert settings_tab.handle_delete_rule(ctx, None)[0].startswith("⚠️")

    def test_save(self, ctx):
        import_tab.handle_paste(ctx, HDFC)
        out = settings_tab.handle_save(ctx, ["sbi"], True, "qwen", True)
        assert "Deleted the text of 1" in out
        assert "hdfc" in ctx.settings.disabled_banks and ctx.settings.llm_model == "qwen"
        assert settings_tab.handle_save(ctx, settings_tab.bank_names(), False, "", False) == (
            "✅ Settings saved."
        )
        assert ctx.settings.disabled_banks == []

    def test_budget(self, ctx):
        assert settings_tab.handle_budget(ctx, "Food", "5,000").startswith("✅")
        assert ctx.settings.budgets == {"Food": 500000}
        assert "removed" in settings_tab.handle_budget(ctx, "Food", "0")
        assert settings_tab.handle_budget(ctx, None, "1").startswith("⚠️")
        assert settings_tab.handle_budget(ctx, "Food", "x").startswith("⚠️")

    @pytest.mark.parametrize("kind,suffix", [("csv", ".csv"), ("json", ".json"), ("backup", ".db")])
    def test_export(self, ctx, tmp_path, kind, suffix):
        out = Path(settings_tab.handle_export(ctx, kind, tmp_path))
        assert out.exists() and out.suffix == suffix

    def test_export_default_dir_and_unknown(self, ctx):
        assert Path(settings_tab.handle_export(ctx, "csv")).exists()
        with pytest.raises(ValueError):
            settings_tab.handle_export(ctx, "pdf")

    def test_bank_names(self):
        assert "hdfc" in settings_tab.bank_names()


class TestApp:
    def test_every_tab_builds(self, ctx):
        app = build_app(ctx)
        assert isinstance(app, gr.Blocks)
        labels = [b.label for b in app.blocks.values() if isinstance(b, gr.Tab)]
        assert labels == ["Import", "Inbox", "Groups", "Settle up", "Insights", "Settings"]
        assert len(TABS) == 6

    def test_demo_banner(self, tmp_path):
        demo = make_ctx(None, demo=True)
        app = build_app(demo)
        md = [b.value for b in app.blocks.values() if isinstance(b, gr.Markdown)]
        assert any("Demo mode" in (v or "") for v in md)

    def test_launch_kwargs_safe_defaults(self):
        kw = launch_kwargs()
        assert kw["server_name"] == "127.0.0.1" and kw["share"] is False and "auth" not in kw

    def test_launch_kwargs_network_needs_password(self):
        with pytest.raises(ValueError):
            launch_kwargs("0.0.0.0")
        assert launch_kwargs("0.0.0.0", password="pw")["auth"] == ("hisaab", "pw")


def test_server_serves_page(ctx):
    """Launch for real on localhost and fetch the page (Gradio client smoke test)."""
    import urllib.request

    app = build_app(ctx)
    kw = launch_kwargs()
    kw.pop("server_port")
    app.launch(prevent_thread_lock=True, quiet=True, **kw)
    try:
        with urllib.request.urlopen(app.local_url, timeout=20) as resp:
            assert resp.status == 200 and b"Hisaab" in resp.read()
    finally:
        app.close()
