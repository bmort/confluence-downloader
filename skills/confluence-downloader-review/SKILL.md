---
name: confluence-downloader-review
description: Fetch Confluence Data Center pages as local PDFs with the confluence-downloader CLI before reviewing them with an agent. Use when the user asks to review, summarize, audit, compare, analyze, or work from Confluence pages, page trees, spaces, or bulk page configs, especially when pages may not already be downloaded locally and should be pulled only if missing or changed.
---

# Confluence Downloader Review

## Core Workflow

Use the local `confluence-downloader` CLI to make sure the requested Confluence pages exist as PDFs before starting content review. Run commands from the `confluence-downloader` repository root, or pass `--repo /path/to/confluence-downloader` to the helper script.

1. Identify the request shape:
   - Bulk config supplied or implied: use `bulk`.
   - Space plus page titles: use `download` for ad hoc pulls, or create a temporary bulk config when version-aware skipping matters.
   - Space tree discovery: use `list-space` first, optionally writing a bulk config, then run `bulk`.
2. Check authentication before network calls: `CONFLUENCE_BASE_URL` and `CONFLUENCE_PAT` should be set, unless the user provides `--base-url` and `--token` explicitly.
3. Use existing downloads by default. Do not pass `--force` unless the user asks to refresh or stale PDFs are suspected.
4. After downloading, inspect `downloaded_pages.md` and the PDF files under the output directory. Use the PDF skill or normal PDF extraction tools for review.
5. Report which files were reviewed and whether any downloads failed or were skipped.

## Recommended Commands

Run commands from the `confluence-downloader` repository root and set the macOS WeasyPrint library path:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run confluence-downloader bulk --config pages.json --output-dir ./pdfs --verbosity normal
```

For one or more named pages:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run confluence-downloader download --space DOC --title "Architecture Overview" --output-dir ./pdfs
```

For a page tree as one combined PDF:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run confluence-downloader download --space DOC --title "Architecture Overview" --include-children --output-dir ./pdfs
```

For discovery and repeatable future pulls:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run confluence-downloader list-space --space DOC --depth 2 --bulk-config pages.json
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run confluence-downloader bulk --config pages.json --output-dir ./pdfs
```

## Helper Script

Use `scripts/ensure_confluence_pdfs.py` for repeatable setup. It wraps the CLI, chooses `bulk` or `download`, verifies environment variables, prints expected output locations, and leaves review decisions to the agent.

Examples:

```bash
python skills/confluence-downloader-review/scripts/ensure_confluence_pdfs.py \
  --config pages.json \
  --output-dir pdfs
```

```bash
python skills/confluence-downloader-review/scripts/ensure_confluence_pdfs.py \
  --space DOC \
  --title "Architecture Overview" \
  --include-children \
  --output-dir pdfs
```

Add `--force` only when the user explicitly wants fresh downloads. Use `--dry-run` to preview the command without contacting Confluence.

## Review Handoff

After the downloader runs:

- Read `<output-dir>/<SPACE>/downloaded_pages.md` to map page titles and IDs to PDF filenames.
- Review the generated PDFs, not Confluence live pages, unless download failed and the user agrees to a fallback.
- If a PDF already existed or was unchanged, treat it as valid review input and mention that it was reused.
- If download failures occurred, continue reviewing successful PDFs and clearly list the missing pages.

## Detailed Reference

Read `references/confluence-downloader-cli.md` when command options, bulk config shape, skip behavior, or output layout are needed.
