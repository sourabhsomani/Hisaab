# Contributing to Hisaab

Thanks for helping! The most useful first contribution is **adding your bank's SMS format**.

## Set up

```bash
git clone https://github.com/<you>/hisaab && cd hisaab
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest            # everything should pass
ruff check .
```

## Add your bank in 15 minutes

1. **Anonymize your SMS.** Export with *SMS Backup & Restore*, then run
   `hisaab anonymize sms.xml -o safe.xml`. Account numbers, names, UPI IDs and reference
   numbers are replaced. Never commit real messages.
2. **Create the plugin** `hisaab/parsers/banks/<bank>.py`, copying `hdfc.py`:

   ```python
   from hisaab.core.models import Direction
   from hisaab.parsers.banks._base import P, match_first

   BANK = "Example Bank"
   SENDERS = ["EXMPLB"]          # the part after "AX-" in the sender ID

   PATTERNS = [
       P(r"Rs\.?(?P<amount>[\d,.]+) debited from A/c X*(?P<acct>\d{4}) to (?P<name>.+?) "
         r"Ref (?P<ref>\d+)", Direction.DEBIT),
   ]

   def parse(body):
       return match_first(body, PATTERNS, BANK)
   ```

   Named groups: `amount` (required), `dir`, `acct`, `name`, `vpa`, `ref`, `date`, `bal`,
   `merchant`. Anything you don't capture is filled in by the generic extractors.
3. **Add fixtures** `tests/fixtures/sms/<bank>.json` with each message and the fields you
   expect (copy any existing file). Include debits *and* credits.
4. **Run** `pytest tests/test_banks.py`. The suite checks your plugin, makes sure it does not
   claim other banks' SMS, and the accuracy report shows your numbers.
5. Open a pull request. CI posts the parser accuracy table on it.

## Code rules

- Core logic (`hisaab/core`, `hisaab/parsers`) never imports Gradio.
- Money is always integer paise. Use `hisaab.core.money` for parsing and formatting.
- Every new function gets a unit test. Splits and settlement changes need property tests.
- Never log SMS bodies, UPI IDs or reference numbers.

## Commit style

We use [Conventional Commits](https://www.conventionalcommits.org): `feat(parsers): ...`,
`fix(core): ...`, `docs: ...`. One feature per pull request.
