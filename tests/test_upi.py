import io

import pytest
from PIL import Image

from hisaab.core.upi import (
    PaymentLine,
    build_upi_link,
    is_valid_vpa,
    parse_upi_link,
    qr_image,
    qr_png,
    whatsapp_summary,
)


class TestVpa:
    @pytest.mark.parametrize(
        "vpa", ["rahul@okaxis", "98765.43210@ybl", "a.b-c_d@paytm", " x1@upi "]
    )
    def test_valid(self, vpa):
        assert is_valid_vpa(vpa)

    @pytest.mark.parametrize(
        "vpa", ["", None, "rahul", "@okaxis", "rahul@", "ra hul@ok", "r@1bank"]
    )
    def test_invalid(self, vpa):
        assert not is_valid_vpa(vpa)


class TestBuildLink:
    def test_matches_design_doc(self):
        link = build_upi_link("rahul@okaxis", "Rahul Kumar", 45000, "Hisaab Goa trip")
        assert link == (
            "upi://pay?pa=rahul@okaxis&pn=Rahul%20Kumar&am=450.00&cu=INR&tn=Hisaab%20Goa%20trip"
        )

    def test_no_note(self):
        assert "tn=" not in build_upi_link("a@ybl", "A", 100)

    def test_name_falls_back_to_handle(self):
        assert "pn=asha" in build_upi_link("asha@ybl", "  ", 100)

    def test_note_trimmed_and_collapsed(self):
        link = build_upi_link("a@ybl", "A", 100, "x " * 100)
        assert len(parse_upi_link(link)["tn"]) <= 50

    def test_special_characters_encoded(self):
        link = build_upi_link("a@ybl", "A&B", 100, "rent=half")
        params = parse_upi_link(link)
        assert params["pn"] == "A&B" and params["tn"] == "rent=half"

    def test_rejects_bad_vpa(self):
        with pytest.raises(ValueError):
            build_upi_link("nope", "A", 100)

    @pytest.mark.parametrize("amount", [0, -100])
    def test_rejects_non_positive(self, amount):
        with pytest.raises(ValueError):
            build_upi_link("a@ybl", "A", amount)


class TestParseLink:
    def test_round_trip(self):
        p = parse_upi_link(build_upi_link("rahul@okaxis", "Rahul Kumar", 12345, "Goa"))
        assert p == {
            "pa": "rahul@okaxis",
            "pn": "Rahul Kumar",
            "am": "123.45",
            "cu": "INR",
            "tn": "Goa",
        }

    def test_rejects_other_scheme(self):
        with pytest.raises(ValueError):
            parse_upi_link("https://pay?pa=x")


class TestQr:
    def test_png_is_png(self):
        data = qr_png("upi://pay?pa=a@ybl&am=1.00")
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert Image.open(io.BytesIO(data)).size[0] > 50

    def test_image_box_size_scales(self):
        small = qr_image("upi://pay?pa=a@ybl", box_size=2)
        big = qr_image("upi://pay?pa=a@ybl", box_size=8)
        assert big.size[0] == small.size[0] * 4


class TestWhatsapp:
    def test_with_lines(self):
        text = whatsapp_summary(
            "Goa trip",
            [
                PaymentLine("Priya", "Rahul", 45000, "upi://pay?pa=r@ybl"),
                PaymentLine("Amit", "Rahul", 123456700),
            ],
        )
        assert text.splitlines()[0] == "*Hisaab · Goa trip*"
        assert "1. Priya → Rahul: ₹450.00" in text
        assert "   Pay: upi://pay?pa=r@ybl" in text
        assert "2. Amit → Rahul: ₹12,34,567.00" in text
        assert "in 2 payment(s)" in text

    def test_settled(self):
        assert "All settled up" in whatsapp_summary("Flat", [])
