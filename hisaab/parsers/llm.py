"""Optional local LLM (Ollama's OpenAI-compatible API) for SMS the rules cannot read.

Off by default. To keep the "nothing leaves your machine" promise, only loopback URLs are
accepted unless ``allow_remote=True`` is passed explicitly.
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from hisaab.core.models import Direction
from hisaab.core.money import to_paise
from hisaab.parsers.types import ParsedTxn

LLM_MAX_CONFIDENCE = 0.75
LLM_EXTRACT_CONFIDENCE = 0.6

Transport = Callable[[str, dict, float], dict]


@dataclass(frozen=True)
class LLMConfig:
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = "llama3.2"
    timeout: float = 20.0
    allow_remote: bool = False


def is_local_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


def http_transport(url: str, payload: dict, timeout: float) -> dict:  # pragma: no cover
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def chat(config: LLMConfig, system: str, user: str, transport: Transport | None = None) -> str:
    """Send one chat completion and return the assistant text."""
    if not config.allow_remote and not is_local_url(config.base_url):
        raise PermissionError("refusing to send SMS to a non-local LLM; set allow_remote=True")
    payload = {
        "model": config.model,
        "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    url = config.base_url.rstrip("/") + "/chat/completions"
    data = (transport or http_transport)(url, payload, config.timeout)
    return data["choices"][0]["message"]["content"]


def extract_json(text: str) -> dict | None:
    """First JSON object in a model reply (models like to wrap JSON in prose or fences)."""
    for m in re.finditer(r"\{.*?\}", text, re.DOTALL):
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


CATEGORY_PROMPT = (
    "You categorize Indian bank transactions. Reply with JSON only: "
    '{"category": <one of the given categories>, "confidence": <0..1>}.'
)
EXTRACT_PROMPT = (
    "Extract the transaction from this Indian bank SMS. Reply with JSON only: "
    '{"direction": "debit"|"credit", "amount": <rupees number>, "account_tail": <last 4 digits '
    'or null>, "counterparty": <name or null>, "upi_ref": <digits or null>}. '
    'If it is not a completed transaction reply {"direction": null}.'
)


def make_categorizer(
    config: LLMConfig, transport: Transport | None = None
) -> Callable[[ParsedTxn, list[str]], tuple[str | None, float]]:
    """Build a categorizer for :class:`hisaab.parsers.categorize.Categorizer`."""

    def categorize(txn: ParsedTxn, categories: list[str]) -> tuple[str | None, float]:
        desc = ", ".join(filter(None, [txn.merchant, txn.counterparty_name, txn.counterparty_vpa]))
        user = f"Categories: {categories}\nTransaction: {txn.direction.value} to {desc}"
        obj = extract_json(chat(config, CATEGORY_PROMPT, user, transport)) or {}
        cat = obj.get("category")
        if cat not in categories:
            return None, 0.0
        try:
            conf = float(obj.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        return cat, round(max(0.0, min(conf, LLM_MAX_CONFIDENCE)), 2)

    return categorize


def make_extractor(
    config: LLMConfig, transport: Transport | None = None
) -> Callable[[str], ParsedTxn | None]:
    """Build an extractor for :class:`hisaab.parsers.pipeline.Pipeline` (``llm_extract``)."""

    def extract(body: str) -> ParsedTxn | None:
        obj = extract_json(chat(config, EXTRACT_PROMPT, body, transport)) or {}
        try:
            direction = Direction(obj.get("direction"))
            amount = to_paise(obj["amount"])
        except (ValueError, KeyError, TypeError):
            return None
        if amount <= 0:
            return None
        tail = obj.get("account_tail")
        ref = obj.get("upi_ref")
        return ParsedTxn(
            direction=direction,
            amount_paise=amount,
            account_tail=str(tail)[-4:] if tail else None,
            counterparty_name=obj.get("counterparty") or None,
            upi_ref=str(ref) if ref and str(ref).isdigit() else None,
            bank="llm",
            confidence=LLM_EXTRACT_CONFIDENCE,
        )

    return extract
