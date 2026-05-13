#!/usr/bin/env python3
"""Ensure requested Confluence pages are available as local PDFs for review."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO = Path.cwd()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO, help="confluence-downloader repository path")
    parser.add_argument("--output-dir", type=Path, default=Path("pdfs"), help="directory where PDFs are written")
    parser.add_argument("--config", type=Path, help="bulk JSON config to download")
    parser.add_argument("--space", help="Confluence space key for direct download")
    parser.add_argument("--title", action="append", default=[], help="Confluence page title; repeat for multiple pages")
    parser.add_argument("--titles-file", type=Path, help="newline-delimited titles file")
    parser.add_argument("--include-children", action="store_true", help="include descendant pages for direct download")
    parser.add_argument("--separate-pages", action="store_true", help="write one PDF per page instead of combined child PDFs")
    parser.add_argument("--download-html", action="store_true", help="also write one HTML copy per Confluence page")
    parser.add_argument("--force", action="store_true", help="regenerate even when files or manifest entries allow skipping")
    parser.add_argument("--dry-run", action="store_true", help="print the downloader command without running it")
    parser.add_argument("--verbosity", default="normal", choices=("quiet", "normal", "verbose"), help="CLI verbosity")
    parser.add_argument("--request-delay", type=float, help="minimum delay between Confluence requests")
    parser.add_argument("--retry-backoff", type=float, help="initial HTTP 429 retry backoff")
    parser.add_argument("--max-retries", type=int, help="maximum HTTP 429 retries")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.repo.exists():
        print(f"ERROR: repo not found: {args.repo}", file=sys.stderr)
        return 2

    if bool(args.config) == bool(args.space or args.title or args.titles_file):
        print("ERROR: provide either --config for bulk mode, or --space with --title/--titles-file for direct mode", file=sys.stderr)
        return 2

    missing_env = [name for name in ("CONFLUENCE_BASE_URL", "CONFLUENCE_PAT") if not os.environ.get(name)]
    if missing_env:
        print("ERROR: missing environment variable(s): " + ", ".join(missing_env), file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["DYLD_FALLBACK_LIBRARY_PATH"] = _prepend_path(env.get("DYLD_FALLBACK_LIBRARY_PATH"), "/opt/homebrew/lib")

    command = ["uv", "run", "confluence-downloader"]
    if args.config:
        command.extend(["bulk", "--config", str(args.config), "--output-dir", str(args.output_dir), "--verbosity", args.verbosity])
    else:
        if not args.space:
            print("ERROR: --space is required for direct mode", file=sys.stderr)
            return 2
        if not args.title and not args.titles_file:
            print("ERROR: provide --title or --titles-file for direct mode", file=sys.stderr)
            return 2
        command.extend(["download", "--space", args.space, "--output-dir", str(args.output_dir), "--verbosity", args.verbosity])
        for title in args.title:
            command.extend(["--title", title])
        if args.titles_file:
            command.extend(["--titles-file", str(args.titles_file)])
        if args.include_children:
            command.append("--include-children")
        if args.separate_pages:
            command.append("--separate-pages")

    if args.force:
        command.append("--force")
    if args.download_html:
        command.append("--download-html")
    if args.request_delay is not None:
        command.extend(["--request-delay", str(args.request_delay)])
    if args.retry_backoff is not None:
        command.extend(["--retry-backoff", str(args.retry_backoff)])
    if args.max_retries is not None:
        command.extend(["--max-retries", str(args.max_retries)])

    print("Running: " + " ".join(_quote_for_display(part) for part in command))
    if args.dry_run:
        return 0

    completed = subprocess.run(command, cwd=args.repo, env=env, check=False)
    if completed.returncode != 0:
        return completed.returncode

    output_dir = args.output_dir if args.output_dir.is_absolute() else args.repo / args.output_dir
    print(f"Output directory: {output_dir}")
    manifest = output_dir / "downloaded_pages.md"
    if manifest.exists():
        print(f"Manifest file: {manifest}")
    return 0


def _prepend_path(existing: str | None, value: str) -> str:
    if not existing:
        return value
    parts = existing.split(os.pathsep)
    if value in parts:
        return existing
    return value + os.pathsep + existing


def _quote_for_display(value: str) -> str:
    if not value or any(character.isspace() for character in value):
        return repr(value)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
