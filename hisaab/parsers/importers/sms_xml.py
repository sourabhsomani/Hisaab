"""Import an *SMS Backup & Restore* XML export. Only inbox SMS from bank senders are kept."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from defusedxml import ElementTree

from hisaab.parsers.filter import is_bank_sender
from hisaab.parsers.pipeline import Message

IST = ZoneInfo("Asia/Kolkata")
INBOX = "1"


def epoch_ms_to_local(ms: int | str, tz: ZoneInfo = IST) -> datetime:
    """Convert Android's millisecond timestamp to a naive local (IST by default) datetime."""
    dt = datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).astimezone(tz)
    return dt.replace(tzinfo=None, microsecond=0)


def _read(source: str | bytes | Path) -> bytes:
    if isinstance(source, Path):
        return source.read_bytes()
    if isinstance(source, str) and not source.lstrip().startswith("<"):
        return Path(source).read_bytes()
    return source.encode("utf-8") if isinstance(source, str) else source


def parse_sms_xml(source: str | bytes | Path, banks_only: bool = True) -> list[Message]:
    """Read every ``<sms>`` element. ``source`` is a path, XML text or bytes.

    defusedxml blocks entity-expansion and external-entity attacks from untrusted files.
    """
    root = ElementTree.fromstring(_read(source))
    out: list[Message] = []
    for sms in root.iter("sms"):
        if sms.get("type", INBOX) != INBOX:
            continue
        sender = (sms.get("address") or "").strip()
        if banks_only and (not sender or not is_bank_sender(sender)):
            continue
        body = sms.get("body") or ""
        date = sms.get("date")
        received = epoch_ms_to_local(date) if date and date.isdigit() else None
        out.append(Message(sender=sender, body=body, received_at=received))
    return out


def split_pasted(text: str) -> list[Message]:
    """Split pasted SMS on blank lines; a first line like ``AX-HDFCBK:`` becomes the sender."""
    messages: list[Message] = []
    for block in [b.strip() for b in text.replace("\r\n", "\n").split("\n\n")]:
        if not block:
            continue
        first, _, rest = block.partition("\n")
        head = first.strip().rstrip(":")
        if rest and is_bank_sender(head) and " " not in head:
            messages.append(Message(sender=head.upper(), body=" ".join(rest.split())))
        else:
            messages.append(Message(sender="", body=" ".join(block.split())))
    return messages
