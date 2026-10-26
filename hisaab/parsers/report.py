"""Parser accuracy report over the fixture corpus. CI posts its markdown on every PR.

Usage: ``python -m hisaab.parsers.report [fixtures_dir]``
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from hisaab.parsers.types import ParsedTxn

FIELDS = (
    "direction",
    "amount_paise",
    "account_tail",
    "counterparty_name",
    "counterparty_vpa",
    "upi_ref",
    "txn_at",
)
DEFAULT_DIR = Path("tests/fixtures/sms")


@dataclass
class BankScore:
    bank: str
    messages: int = 0
    parsed: int = 0
    correct: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELDS, 0))

    @property
    def field_accuracy(self) -> float:
        total = self.messages * len(FIELDS)
        return sum(self.correct.values()) / total if total else 1.0

    def accuracy(self, name: str) -> float:
        return self.correct[name] / self.messages if self.messages else 1.0


def load_fixtures(directory: Path = DEFAULT_DIR) -> dict[str, list[dict]]:
    """Map bank name to its fixture messages (skips negatives.json)."""
    out: dict[str, list[dict]] = {}
    for path in sorted(Path(directory).glob("*.json")):
        if path.stem == "negatives":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        out[data["bank"]] = data["messages"]
    return out


def score_message(txn: ParsedTxn | None, expected: dict) -> dict[str, bool]:
    """Which fields of one parsed message match the expectation."""
    got = txn.as_dict() if txn else {}
    return {f: got.get(f) == expected.get(f) for f in FIELDS}


def evaluate(
    fixtures: dict[str, list[dict]], parse: Callable[[str, str], ParsedTxn | None]
) -> list[BankScore]:
    """Run ``parse(sender, body)`` over every fixture and score each field."""
    scores = []
    for bank, messages in fixtures.items():
        s = BankScore(bank)
        for msg in messages:
            txn = parse(msg["sender"], msg["body"])
            s.messages += 1
            s.parsed += txn is not None
            for name, ok in score_message(txn, msg["expected"]).items():
                s.correct[name] += ok
        scores.append(s)
    return scores


def overall(scores: list[BankScore]) -> float:
    total = sum(s.messages for s in scores) * len(FIELDS)
    return sum(sum(s.correct.values()) for s in scores) / total if total else 1.0


def to_markdown(scores: list[BankScore]) -> str:
    lines = [
        "## Parser accuracy",
        "",
        "| Bank | SMS | Parsed | Amount | Direction | Field accuracy |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for s in scores:
        lines.append(
            f"| {s.bank} | {s.messages} | {s.parsed} | {s.accuracy('amount_paise'):.0%} | "
            f"{s.accuracy('direction'):.0%} | {s.field_accuracy:.1%} |"
        )
    lines += ["", f"**Overall field accuracy: {overall(scores):.1%}** (target ≥ 95%)"]
    return "\n".join(lines)


def pipeline_parser() -> Callable[[str, str], ParsedTxn | None]:
    from hisaab.parsers.pipeline import default_pipeline

    pipe = default_pipeline()
    return lambda sender, body: pipe.extract(sender, body)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    directory = Path(argv[0]) if argv else DEFAULT_DIR
    scores = evaluate(load_fixtures(directory), pipeline_parser())
    print(to_markdown(scores))
    return 0 if overall(scores) >= 0.95 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
