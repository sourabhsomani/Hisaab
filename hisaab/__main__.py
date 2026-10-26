"""Command line: ``hisaab`` launches the app; ``hisaab anonymize`` masks an SMS backup."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hisaab import __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hisaab", description="Open-source expense splitter.")
    p.add_argument("--version", action="version", version=f"hisaab {__version__}")
    sub = p.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the web app (default)")
    for target in (p, serve):
        target.add_argument(
            "--db",
            type=Path,
            default=None,
            help="SQLite file (default ~/.hisaab/hisaab.db or $HISAAB_DB)",
        )
        target.add_argument(
            "--host",
            default="127.0.0.1",
            help="bind address; anything but localhost needs --password",
        )
        target.add_argument("--port", type=int, default=7860)
        target.add_argument("--password", default=None, help="login password (user: hisaab)")
        target.add_argument(
            "--demo", action="store_true", help="in-memory database with synthetic data"
        )

    anon = sub.add_parser("anonymize", help="mask an SMS Backup & Restore XML for sharing")
    anon.add_argument("src", type=Path)
    anon.add_argument("-o", "--output", type=Path, default=None)

    bak = sub.add_parser("backup", help="copy the database to a file")
    bak.add_argument("dest", type=Path)
    bak.add_argument("--db", type=Path, default=None)
    return p


def cmd_anonymize(src: Path, output: Path | None) -> int:
    from hisaab.parsers.anonymize import Anonymizer

    dest = output or src.with_name(f"{src.stem}.anonymized{src.suffix}")
    n = Anonymizer().anonymize_xml(src, dest)
    print(f"Masked {n} SMS -> {dest}")
    print("Check the file before sharing: names in unusual places may need a manual pass.")
    return 0


def cmd_backup(dest: Path, db: Path | None) -> int:
    from hisaab.core.db import backup_db, get_engine

    out = backup_db(get_engine(db), dest)
    print(f"Backup written to {out}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:  # pragma: no cover - starts a server
    from hisaab.app import build_app, launch_kwargs, make_ctx

    ctx = make_ctx(args.db, demo=args.demo)
    if args.demo:
        from hisaab.demo import seed_demo

        with ctx.session() as s:
            seed_demo(s)
    kwargs = launch_kwargs(args.host, args.port, args.password, demo=args.demo)
    build_app(ctx).launch(**kwargs)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "anonymize":
        return cmd_anonymize(args.src, args.output)
    if args.command == "backup":
        return cmd_backup(args.dest, args.db)
    return cmd_serve(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
