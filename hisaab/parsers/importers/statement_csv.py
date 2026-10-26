"""Import bank statements (CSV or Excel) as a fallback source of transactions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from hisaab.core.models import Direction
from hisaab.core.money import parse_amount
from hisaab.core.upi import is_valid_vpa
from hisaab.parsers import fields
from hisaab.parsers.types import ParsedTxn

STATEMENT_CONFIDENCE = 0.9

_ALIASES = {
    "date": ["txn date", "transaction date", "value date", "date", "value dt", "tran date"],
    "description": [
        "narration",
        "description",
        "particulars",
        "remarks",
        "details",
        "transaction remarks",
        "transaction details",
    ],
    "debit": [
        "withdrawal amt",
        "withdrawal amount",
        "withdrawal",
        "debit amount",
        "debit",
        "dr amount",
        "dr",
    ],
    "credit": [
        "deposit amt",
        "deposit amount",
        "deposit",
        "credit amount",
        "credit",
        "cr amount",
        "cr",
    ],
    "amount": ["amount", "transaction amount", "amount (inr)"],
    "type": ["type", "dr/cr", "cr/dr", "transaction type"],
    "ref": ["chq./ref.no.", "ref no", "reference no", "ref no./cheque no.", "utr", "chq no"],
}


@dataclass(frozen=True)
class Columns:
    date: str
    description: str
    debit: str | None = None
    credit: str | None = None
    amount: str | None = None
    type: str | None = None
    ref: str | None = None


def _norm(header: object) -> str:
    """Lowercase, drop dots, collapse spaces: ``Withdrawal Amt.`` -> ``withdrawal amt``."""
    return re.sub(r"\s+", " ", str(header).replace(".", " ")).strip().lower()


def detect_columns(headers: list[object]) -> Columns:
    """Map a statement's headers to our fields; raises ``ValueError`` if it cannot."""
    normed = {_norm(h): str(h) for h in headers}
    found: dict[str, str] = {}
    for key, aliases in _ALIASES.items():
        for alias in map(_norm, aliases):
            if alias in normed and normed[alias] not in found.values():
                found[key] = normed[alias]
                break
    if "date" not in found or "description" not in found:
        raise ValueError("statement needs a date and a narration/description column")
    if not (("debit" in found or "credit" in found) or "amount" in found):
        raise ValueError("statement needs debit/credit columns or an amount column")
    return Columns(**found)


def find_header_row(frame: pd.DataFrame, max_scan: int = 40) -> int:
    """Banks put a preamble above the table; find the first row that looks like headers."""
    for i in range(min(max_scan, len(frame))):
        try:
            detect_columns(list(frame.iloc[i].values))
            return i
        except ValueError:
            continue
    raise ValueError("could not find the statement's header row")


def read_table(path: str | Path) -> pd.DataFrame:
    """Load CSV or Excel and return a frame whose columns are the statement headers."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        raw = pd.read_excel(path, header=None, dtype=str)
    else:
        raw = pd.read_csv(
            path,
            header=None,
            dtype=str,
            skip_blank_lines=False,
            on_bad_lines="skip",
            engine="python",
        )
    row = find_header_row(raw)
    frame = raw.iloc[row + 1 :].copy()
    frame.columns = [str(c) for c in raw.iloc[row].values]
    return frame.dropna(how="all")


def _amount(value: object) -> int:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0
    text = str(value).strip()
    if not text or text.lower() in ("nan", "-", "0", "0.00"):
        return 0
    try:
        return abs(parse_amount(text))
    except ValueError:
        return 0


def parse_narration(text: str) -> tuple[str | None, str | None, str | None]:
    """Pull (name, vpa, ref) out of UPI narrations.

    ``UPI-RAHUL KUMAR-rahul@okaxis-HDFC0001234-429812345678-PAYMENT`` or
    ``UPI/429812345678/RAHUL KUMAR/rahul@okaxis``.
    """
    parts = [p.strip() for p in re.split(r"[/\-]", text) if p.strip()]
    vpa = next((p.lower() for p in parts if is_valid_vpa(p)), None) or fields.find_vpa(text)
    ref_match = re.search(r"(?<!\d)(\d{12})(?!\d)", text)
    ref = ref_match.group(1) if ref_match else None
    name = None
    if re.match(r"(?i)\s*upi", text):
        for part in parts[1:]:
            if re.fullmatch(r"[A-Za-z][A-Za-z .&']{1,40}", part) and part.upper() not in (
                "UPI",
                "PAYMENT",
                "SENT",
                "RECEIVED",
                "P2A",
                "P2M",
                "DR",
                "CR",
                "PAY",
            ):
                name = fields.clean_name(part)
                break
    return name, vpa, ref


def row_to_txn(row: pd.Series, cols: Columns) -> ParsedTxn | None:
    """Convert one statement row; returns ``None`` for rows without an amount."""
    desc = str(row.get(cols.description, "") or "")
    debit = _amount(row.get(cols.debit)) if cols.debit else 0
    credit = _amount(row.get(cols.credit)) if cols.credit else 0
    if not debit and not credit and cols.amount:
        amt = _amount(row.get(cols.amount))
        kind = str(row.get(cols.type, "") or "").strip().lower() if cols.type else ""
        is_credit = kind.startswith("c") or "cr" in kind
        debit, credit = (0, amt) if is_credit else (amt, 0)
    if not debit and not credit:
        return None
    direction = Direction.DEBIT if debit else Direction.CREDIT
    name, vpa, ref = parse_narration(desc)
    raw_ref = str(row.get(cols.ref, "") or "").strip().lstrip("0") if cols.ref else ""
    if not ref and raw_ref.isdigit() and len(raw_ref) >= 9:
        ref = raw_ref
    date = fields.parse_sms_date(str(row.get(cols.date, "")))
    return ParsedTxn(
        direction=direction,
        amount_paise=debit or credit,
        counterparty_name=name,
        counterparty_vpa=vpa,
        upi_ref=ref,
        txn_at=date,
        merchant=None if name else (fields.clean_name(desc[:40]) or None),
        bank="statement",
        confidence=STATEMENT_CONFIDENCE,
    )


def import_statement(path: str | Path) -> list[ParsedTxn]:
    """Read a statement file and return one ParsedTxn per money-moving row."""
    frame = read_table(path)
    cols = detect_columns(list(frame.columns))
    txns = [row_to_txn(row, cols) for _, row in frame.iterrows()]
    return [t for t in txns if t is not None]
