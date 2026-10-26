"""Mask account numbers, names, UPI IDs, phone and reference numbers so real SMS formats
can be shared safely as fixtures. Amounts, dates and wording are kept so parsers still work.

The same original value always maps to the same fake within one run (so paired SMS still
dedupe), but a fresh random salt is used per run, so fakes cannot be reversed.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path
from xml.etree.ElementTree import tostring

from defusedxml import ElementTree

from hisaab.parsers import fields

FAKE_NAMES = [
    "RAVI SHARMA",
    "ANITA VERMA",
    "KARAN MEHTA",
    "NEHA GUPTA",
    "ARJUN NAIR",
    "POOJA IYER",
    "VIKRAM SINGH",
    "MEERA JOSHI",
    "ROHAN DAS",
    "SNEHA REDDY",
    "ADITYA RAO",
    "KAVYA PILLAI",
]

_ACCOUNT = re.compile(
    r"(?i)(\b(?:a/?c|acct|account|card)(?:\s*no\.?)?\s*(?:ending(?: with)?)?\s*[*xX.]*\s*)"
    r"(\d{3,18})"
)
_LONG_NUMBER = re.compile(r"(?<!\d)(\d{9,18})(?!\d)")
_MOBILE = re.compile(r"(?<!\d)(?:\+?91[- ]?)?([6-9]\d{9})(?!\d)")
_VPA = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9.\-_]*)@([A-Za-z][A-Za-z0-9]{1,63})\b")
_HELPLINE = re.compile(r"^1800\d{6,7}$")


class Anonymizer:
    def __init__(self, salt: str | None = None) -> None:
        self.salt = salt if salt is not None else secrets.token_hex(16)
        self._names: dict[str, str] = {}

    def _digits(self, original: str, length: int) -> str:
        """Deterministic fake digits of ``length`` for ``original`` (never starts with 0)."""
        h = hashlib.sha256(f"{self.salt}|{original}".encode()).hexdigest()
        digits = "".join(str(int(c, 16) % 10) for c in h * 2)[:length]
        return ("1" + digits[1:]) if digits.startswith("0") else digits

    def fake_name(self, real: str) -> str:
        key = " ".join(real.upper().split())
        if key not in self._names:
            idx = int(self._digits(key, 6)) % len(FAKE_NAMES)
            used = set(self._names.values())
            for step in range(len(FAKE_NAMES)):
                cand = FAKE_NAMES[(idx + step) % len(FAKE_NAMES)]
                if cand not in used:
                    break
            else:
                cand = f"PERSON {len(self._names) + 1}"
            self._names[key] = cand
        fake = self._names[key]
        return fake.title() if real.istitle() else fake

    def mask_accounts(self, text: str) -> str:
        return _ACCOUNT.sub(lambda m: m.group(1) + self._digits(m.group(2), len(m.group(2))), text)

    def mask_vpas(self, text: str) -> str:
        def repl(m: re.Match[str]) -> str:
            return f"user{self._digits(m.group(1).lower(), 4)}@{m.group(2)}"

        return _VPA.sub(repl, text)

    def mask_mobiles(self, text: str) -> str:
        return _MOBILE.sub(
            lambda m: m.group(0).replace(m.group(1), "9" + self._digits(m.group(1), 9)), text
        )

    def mask_long_numbers(self, text: str) -> str:
        """UPI refs, UTRs and other long ids; toll-free helplines are kept."""

        def repl(m: re.Match[str]) -> str:
            n = m.group(1)
            return n if _HELPLINE.match(n) else self._digits(n, len(n))

        return _LONG_NUMBER.sub(repl, text)

    def mask_names(self, text: str) -> str:
        for _ in range(5):  # a message rarely has more than a couple of names
            name = fields.find_counterparty(text)
            if not name or name in FAKE_NAMES or name.upper() in FAKE_NAMES:
                break
            if len(name) < 3 or not re.search(r"[A-Za-z]{3}", name):
                break
            text = text.replace(name, self.fake_name(name))
        return text

    def anonymize_text(self, text: str) -> str:
        """Mask everything personal in one SMS body."""
        text = self.mask_vpas(text)
        text = self.mask_accounts(text)
        text = self.mask_mobiles(text)
        text = self.mask_long_numbers(text)
        return self.mask_names(text)

    def anonymize_xml(self, src: str | Path, dest: str | Path) -> int:
        """Rewrite an SMS Backup & Restore XML file. Returns the number of SMS masked."""
        root = ElementTree.parse(str(src)).getroot()
        count = 0
        for sms in root.iter("sms"):
            if sms.get("body"):
                sms.set("body", self.anonymize_text(sms.get("body")))
                count += 1
            for attr in ("contact_name", "address"):
                value = sms.get(attr)
                if value and not re.fullmatch(r"[A-Z]{2}-[A-Z0-9]{3,9}(?:-[A-Z])?", value):
                    sms.set(attr, "(masked)")
        Path(dest).write_bytes(b"<?xml version='1.0' encoding='UTF-8' ?>\n" + tostring(root))
        return count
