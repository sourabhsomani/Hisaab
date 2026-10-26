# Security policy

Hisaab handles bank SMS and UPI IDs, so we treat security reports as a priority.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting
(Security tab → "Report a vulnerability") and include steps to reproduce. You will get an
acknowledgement within 72 hours.

## What Hisaab promises

- The app binds to `127.0.0.1` by default; `--host` requires `--password`.
- `share=True` is never set; Gradio share links are public.
- No telemetry and no network calls, except a local Ollama model when you turn it on.
- SMS bodies, UPI IDs and reference numbers are never written to logs.
- Account numbers are stored only as their last four digits.

Never paste real SMS into an issue. Run `hisaab anonymize` first.
