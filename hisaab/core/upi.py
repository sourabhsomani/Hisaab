"""UPI deep links, QR codes and WhatsApp summaries. Hisaab never moves money."""

from __future__ import annotations

import io
import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlsplit

import qrcode
from PIL.Image import Image

from hisaab.core.money import format_inr, paise_to_decimal_str

_VPA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-_]{0,255}@[A-Za-z][A-Za-z0-9]{1,63}$")
NOTE_MAX = 50


def is_valid_vpa(vpa: str | None) -> bool:
    """True for UPI IDs like ``rahul@okaxis`` or ``98765.43210@ybl``."""
    return bool(vpa) and bool(_VPA.match(vpa.strip()))


def _q(value: str) -> str:
    return quote(value, safe="@.-_")


def build_upi_link(vpa: str, name: str, amount_paise: int, note: str = "") -> str:
    """Build ``upi://pay?pa=..&pn=..&am=..&cu=INR&tn=..`` for an exact amount."""
    if not is_valid_vpa(vpa):
        raise ValueError(f"invalid UPI ID: {vpa!r}")
    if amount_paise <= 0:
        raise ValueError("amount must be positive")
    parts = [
        f"pa={_q(vpa.strip())}",
        f"pn={_q(name.strip() or vpa.split('@')[0])}",
        f"am={paise_to_decimal_str(amount_paise)}",
        "cu=INR",
    ]
    note = " ".join(note.split())[:NOTE_MAX]
    if note:
        parts.append(f"tn={_q(note)}")
    return "upi://pay?" + "&".join(parts)


def parse_upi_link(link: str) -> dict[str, str]:
    """Decode a ``upi://pay`` link into its parameters (handy for tests and import)."""
    parts = urlsplit(link)
    if parts.scheme != "upi" or parts.netloc != "pay":
        raise ValueError("not a upi://pay link")
    return {k: v[0] for k, v in parse_qs(parts.query).items()}


def qr_image(link: str, box_size: int = 8) -> Image:
    """Render a link as a QR code PIL image."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box_size, border=2
    )
    qr.add_data(link)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").get_image()


def qr_png(link: str, box_size: int = 8) -> bytes:
    """Render a link as PNG bytes."""
    buf = io.BytesIO()
    qr_image(link, box_size).save(buf, format="PNG")
    return buf.getvalue()


@dataclass(frozen=True)
class PaymentLine:
    payer: str
    payee: str
    amount_paise: int
    link: str | None = None


def whatsapp_summary(group_name: str, lines: Iterable[PaymentLine]) -> str:
    """Copy-ready WhatsApp text listing who pays whom, with UPI links when available."""
    lines = list(lines)
    header = f"*Hisaab · {group_name}*"
    if not lines:
        return f"{header}\nAll settled up! 🎉"
    body = [header, "Settle up:"]
    total = 0
    for i, ln in enumerate(lines, 1):
        total += ln.amount_paise
        body.append(f"{i}. {ln.payer} → {ln.payee}: {format_inr(ln.amount_paise)}")
        if ln.link:
            body.append(f"   Pay: {ln.link}")
    body.append(f"Total to move: {format_inr(total)} in {len(lines)} payment(s)")
    body.append("_Sent from Hisaab — pay from any UPI app, no sign-up needed._")
    return "\n".join(body)
