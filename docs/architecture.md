# Architecture

Hisaab is three layers. Each only imports the ones below it.

```
hisaab/ui/*, app.py      Gradio widgets. Handlers are plain functions; build() wires them.
        │
hisaab/services/*        The only layer that uses both the database and core logic.
        │
hisaab/core/*            Pure logic and models: money, splits, settle, auto-settle, UPI.
hisaab/parsers/*         Pure SMS pipeline, bank plugins, importers, optional LLM.
```

Core and parsers never import Gradio, so the UI can be swapped (for example to FastAPI, the
open question in the design doc) without touching parsing or the split engine.

## Money

All amounts are integer **paise**. `core/money.py` parses `Rs.1,23,456.00`, `INR 450`, `₹99`
and formats with the Indian numbering system. Floats never touch stored amounts.

## Data model

One SQLite file, nine tables (`core/models.py`): `raw_message`, `transaction`, `category`,
`rule`, `group`, `member`, `expense`, `expense_share`, `settlement`. Datetimes are naive local
time because bank SMS carry IST wall-clock times. **Balances are never stored**; they are
computed from expense shares and confirmed settlements so they always match history.

## SMS pipeline (`parsers/pipeline.py`)

| Stage | Module | Notes |
|---|---|---|
| 1. Filter | `filter.py` | DLT sender check; rejects OTP, failed, request, mandate, reminder, promo |
| 2. Extract | `banks/*.py` → `generic.py` → `llm.py` | Plugins whose `SENDERS` match run first |
| 3. Normalize | `normalize.py` | Gateway prefixes, brand merging via `data/merchants.json` |
| 4. Dedup | `dedup.py` | Same UPI ref, or amount + account tail within 3 minutes |
| 5. Categorize | `categorize.py` | User rules (1.0) → keywords (0.9) → person/credit (0.75) → LLM (≤ 0.75) |

Final confidence is `min(parse confidence, category confidence)`; below 0.7 goes to the Inbox.
Dedup runs within a batch and, in `services/importing.py`, against stored transactions.

### Bank plugins

```python
BANK = "HDFC Bank"
SENDERS = ["HDFCBK"]
PATTERNS = [P(r"...(?P<amount>...)...", Direction.DEBIT), ...]
def parse(body): return match_first(body, PATTERNS, BANK)
```

`banks/_base.py` turns named groups into a `ParsedTxn` and fills uncaptured fields with the
generic extractors. `banks.discover()` finds new plugins automatically.

## Splits (`core/splits.py`)

| Type | Rule |
|---|---|
| equal | `total ÷ n`; leftover paise to the first members |
| exact | must sum to the total |
| percentage | must sum to 100; largest-remainder rounding |
| shares | proportional; largest-remainder rounding |
| adjustment | equal split of the rest after ± per-member amounts |

## Settlement (`core/settle.py`)

`balance = Σ paid − Σ share + Σ settled out − Σ settled in`. Debtors and creditors go in two
heaps; the largest debtor pays the largest creditor the smaller amount, until all are zero.
At most n − 1 payments.

## Auto-settle (`core/autosettle.py`, `services/groups.py`)

For each new credit: candidate debts are planned payments *to the owner*, minus amounts
already proposed. A member matches on exact UPI ID, or fuzzy name/alias (`rapidfuzz.WRatio`
≥ 85). Amount within ₹1 is a full settlement; less is partial; more is no match. Ranking:
full before partial, then identity score, then closest amount. The result is a `proposed`
settlement, which never changes balances until the user confirms it.

## Privacy decisions

- `app.launch_kwargs` refuses non-loopback hosts without a password (except `--demo`).
- `parsers/llm.py` refuses non-loopback LLM URLs unless `allow_remote=True` in code.
- `parsers/anonymize.py` uses a random salt per run so fakes can't be reversed, but stays
  consistent within a run so paired SMS still dedupe.
- Exports skip `raw_message.body`.
