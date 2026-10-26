# Running Hisaab beyond your laptop

## On your phone, at home

Hisaab binds to `127.0.0.1`. To open it from your phone, pick one:

- **Tailscale (recommended).** Install Tailscale on the laptop and phone, then run
  `hisaab --host 0.0.0.0 --password 'something-long'` and open
  `http://<laptop-tailscale-name>:7860`. Traffic stays inside your tailnet.
- **Reverse proxy with login** (Caddy, nginx + basic auth) in front of `127.0.0.1:7860`.

Never use Gradio share links for real data: they are public URLs.

## Hugging Face Spaces demo

The public demo runs only on synthetic data and resets on every restart.

1. Create a Space with the **Gradio** SDK.
2. Copy `app_spaces.py` as the Space's `app.py`, and add a `requirements.txt` containing
   `hisaab` (or `git+https://github.com/sourabhsomani/hisaab`).
3. The Space runs `hisaab --demo --host 0.0.0.0 --port 7860` with an in-memory database.

Do not paste real SMS into the demo.

## Backups

`hisaab backup ~/Backups/hisaab-$(date +%F).db` writes a consistent copy even while the app is
running. The Settings tab offers the same backup plus CSV and JSON exports.
