# Hisaab

**Your bank already texts you every payment. Hisaab turns those texts into splits, and tells
you when your friends have paid you back.**

Hisaab is a free, open-source, self-hostable expense splitter built for how India pays: UPI,
bank SMS alerts and INR. It runs on your own machine, keeps everything in one SQLite file and
never sends your financial data anywhere.

[![CI](https://github.com/sourabhsomani/hisaab/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)

## The loop no other app closes

1. **Capture** — paste bank SMS or import an *SMS Backup & Restore* XML. Hisaab parses debits
   and credits from 11 banks and UPI apps, merges the duplicate SMS your bank *and* UPI app
   both send, and categorizes them.
2. **Split** — send any transaction to a group: equal, exact, percentage, shares or
   adjustment. Every split resolves to exact paise.
3. **Collect** — each debt gets a `upi://pay` link and QR code with the exact amount, plus a
   WhatsApp-ready summary. Friends pay from any UPI app. No sign-up.
4. **Auto-settle** — when your bank texts you "credited by RAHUL KUMAR", Hisaab matches it
   to Rahul's debt and proposes marking it settled. You confirm with one click.

## Quick start

```bash
pip install hisaab
hisaab                 # opens http://127.0.0.1:7860
hisaab --demo          # try it with three months of synthetic SMS
```

From source:

```bash
git clone https://github.com/sourabhsomani/hisaab && cd hisaab
pip install -e ".[dev]"
hisaab --demo
```

| Command | What it does |
|---|---|
| `hisaab` / `hisaab serve` | Run the app on `127.0.0.1:7860` |
| `hisaab --db PATH` | Use another database file (or set `HISAAB_DB`) |
| `hisaab --host 0.0.0.0 --password …` | Reach it from your phone on your network |
| `hisaab anonymize sms.xml` | Mask names, accounts, UPI IDs and refs before sharing |
| `hisaab backup copy.db` | Consistent copy of the database |
| `python -m hisaab.parsers.report` | Parser accuracy table for the fixture corpus |

## The app

| Tab | You can |
|---|---|
| **Import** | Paste SMS, upload SMS XML or a CSV/Excel bank statement, extract expenses from a WhatsApp chat export |
| **Inbox** | Confirm drafts, fix categories ("apply to all from this merchant" creates a rule), split a transaction with a group |
| **Groups** | Create trip/flat/couple groups, add members with UPI IDs and bank-name aliases, add expenses |
| **Settle up** | See balances and the fewest payments, scan UPI QR codes, copy the WhatsApp message, confirm detected repayments |
| **Insights** | Monthly spend, categories, top merchants, budgets |
| **Settings** | Rules, bank toggles, local LLM switch, delete-SMS-text option, budgets, CSV/JSON export, backup |

## Supported banks

HDFC Bank · SBI · ICICI Bank · Axis Bank · Kotak · PNB · Bank of Baroda · Canara Bank ·
Union Bank of India · IDFC FIRST Bank · Paytm Payments Bank. A generic extractor handles
other banks, and anything it can't read waits in the Inbox.

**Your bank missing?** Adding it is a 15-minute first contribution — see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Privacy

- Binds to `127.0.0.1`. Any other host needs `--password`. `share=True` is never used.
- No telemetry, no cloud calls. The optional LLM only talks to a **local** Ollama server; other
  URLs are refused.
- Account numbers are stored as their last four digits. You can have SMS text deleted right
  after parsing, and exports never include it.
- SMS XML is parsed with `defusedxml`.

Read [SECURITY.md](SECURITY.md) for how to report issues.

## How it works

```
SMS ─▶ filter ─▶ extract ─▶ normalize ─▶ dedup ─▶ categorize ─▶ SQLite
        (OTP,     (bank      (RAZ*SWIGGY   (UPI ref /  (rules →
        promo,    plugins →   → Swiggy)    amount+     keywords →
        failed…)  generic →               tail+3 min)  local LLM)
                  local LLM)

expense ─▶ split engine (largest remainder) ─▶ balances ─▶ greedy simplify (≤ n−1 payments)
                                                              └─▶ upi:// links + QR + WhatsApp
credit SMS ─▶ auto-settle matcher (UPI ID or fuzzy name ≥ 85, amount ±₹1) ─▶ proposal ─▶ you confirm
```

Details in [docs/architecture.md](docs/architecture.md).

## Quality

- **594 tests**, 99% line coverage. Every public function has unit tests; splits and debt
  simplification have Hypothesis property tests (shares always sum to the total; every
  balance reaches zero in at most n − 1 payments).
- Each bank plugin has anonymized fixtures with expected fields, a test that it never claims
  another bank's SMS, and a test that fixtures still parse after `hisaab anonymize`.
- CI runs ruff and pytest on Python 3.10–3.13 and posts the parser accuracy table.

The current fixture corpus has 32 labelled SMS (100% field accuracy) plus 9 negatives. The v1
goal is 500 real, anonymized messages — contributions are very welcome.

## Roadmap

| Version | Planned |
|---|---|
| v1.1 | Hinglish quick entry ("kal 600 ka petrol, Rahul aur Priya ke saath"), recurring expenses, SQLCipher encryption |
| v1.2 | Receipt OCR |
| v2 | Android companion that forwards new bank SMS to your self-hosted Hisaab |

Hisaab will never move money or link bank accounts: it only creates UPI links, and your UPI
app does the paying.

## License

[AGPL-3.0](LICENSE). Any hosted fork that reads people's bank messages must publish its
changes.
