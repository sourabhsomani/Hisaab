"""Hugging Face Spaces entry point: the synthetic-data demo, reset on every restart."""

from hisaab.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main(["--demo", "--host", "0.0.0.0", "--port", "7860"]))
