<p align="center">
  <img src="assets/confluence-downloader-logo.png" alt="Confluence Downloader CLI logo" width="400">
</p>

# Confluence Downloader

Turn Confluence Data Center pages into clean PDF context packs for LLM workflows. The CLI
can download one page, many named pages, or whole page trees; combine each page tree into
a single PDF by default; generate bulk download configs from a space tree; and skip
unchanged pages in bulk mode by comparing Confluence versions with the local manifest.

## ✨ What It Does

| Need                                                | Use                                                           |
| --------------------------------------------------- | ------------------------------------------------------------- |
| Download one page                                   | `confluence-downloader download --space KEY --title "Page"`          |
| Download a page and all descendants                 | Add `--include-children`                                      |
| Get one PDF per page instead of a combined tree PDF | Add `--separate-pages`                                        |
| Download pages across multiple spaces               | Use `confluence-downloader bulk --config pages.json`                 |
| Skip pages already downloaded at the same version   | Use bulk mode, which reads `downloaded_pages.md`              |
| Discover pages and build a bulk config              | Use `confluence-downloader list-space --bulk-config pages.json`      |
| Search for matching page titles                     | Use `confluence-downloader search "architecture" --space DOC` |
| Handle rate limits                                  | Add `--request-delay`, `--retry-backoff`, and `--max-retries` |

## 📦 Install

Install from a fresh machine by cloning this repository first:

```bash
git clone git@gitlab.com:benmort/confluence-downloader.git
cd confluence-downloader
```

Install `uv` if it is not already available:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install the CLI and development dependencies:

```bash
uv sync --dev
```

On macOS, the formatted fallback renderer requires WeasyPrint's native Pango libraries:

```bash
brew install pango
```

Check the CLI is available:

```bash
uv run confluence-downloader --help
```

## 🤖 Codex Skill

This repository includes a Codex skill for agent-assisted Confluence page review. See
[`skills/confluence-downloader/README.md`](skills/confluence-downloader/README.md)
for skill installation and usage.

## 🔐 Configure Authentication

Pass the Confluence URL and Personal Access Token as options:

```bash
uv run confluence-downloader download \
  --base-url "https://confluence.example.com/confluence" \
  --token "your-personal-access-token" \
  --space DOC \
  --title "Architecture Overview"
```

Or set environment variables once:

```bash
export CONFLUENCE_BASE_URL="https://confluence.example.com/confluence"
export CONFLUENCE_PAT="your-personal-access-token"
```

`--base-url` can be either the Confluence root URL or a context-path URL such as
`https://host/confluence`.

## 🚀 Quick Start

Download one page:

```bash
uv run confluence-downloader download \
  --space DOC \
  --title "Architecture Overview" \
  --output-dir ./pdfs
```

Download a page plus all descendants. By default, this writes one combined PDF for the
root page tree:

```bash
uv run confluence-downloader download \
  --space DOC \
  --title "Architecture Overview" \
  --include-children \
  --output-dir ./pdfs
```

Write one PDF per page instead:

```bash
uv run confluence-downloader download \
  --space DOC \
  --title "Architecture Overview" \
  --include-children \
  --separate-pages \
  --output-dir ./pdfs
```

Repeat `--title` for multiple root pages:

```bash
uv run confluence-downloader download \
  --space DOC \
  --title "Architecture Overview" \
  --title "ADR Index" \
  --output-dir ./pdfs
```

Or use a newline-delimited titles file:

```bash
uv run confluence-downloader download \
  --space DOC \
  --titles-file titles.txt \
  --output-dir ./pdfs
```

## 🧭 Choosing Download Options

| Option               | Applies to                        | Default                                       | Meaning                                                                           |
| -------------------- | --------------------------------- | --------------------------------------------- | --------------------------------------------------------------------------------- |
| `--include-children` | `download`, `bulk` config entries | Off for `download`; configurable in bulk JSON | Include all descendants, not only direct children                                 |
| `--combine-children` | `download`, `bulk`                | On                                            | Write one combined PDF per requested root when children are included              |
| `--separate-pages`   | `download`, `bulk`                | Off                                           | Write one PDF per page instead of one combined tree PDF                           |
| `--force`            | `download`, `bulk`                | Off                                           | Regenerate even when an existing PDF or manifest version would normally skip work |
| `--verbosity`        | `download`, `bulk`                | `quiet` for download, `normal` for bulk       | Choose `quiet`, `normal`, or `verbose` progress logs                              |

## 📚 Bulk Downloads

Use bulk mode when you have a repeatable set of pages, especially across spaces:

```json
{
  "include_children": true,
  "pages": [
    { "space": "DOC", "title": "Architecture Overview" },
    { "space": "OPS", "title": "Operations Runbook", "include_children": false }
  ]
}
```

Run it:

```bash
uv run confluence-downloader bulk --config pages.json --output-dir ./pdfs
```

Bulk config rules:

- Top-level `"include_children"` is the default for all pages in the file.
- A page entry can override that default with its own `"include_children"` value.
- `--group-by-page` is the default, so each configured page is processed as its own
  progress group.
- `--group-by-space` combines compatible entries into fewer downloader runs.

```bash
uv run confluence-downloader bulk --config pages.json --group-by-space
```

## ✅ Version-Aware Skipping

Bulk mode uses each space's `downloaded_pages.md` manifest as a version cache. Before
downloading a page, it resolves the current Confluence version and compares it with the
manifest row for that page ID.

A page is skipped when all of these are true:

- The manifest contains the same page ID.
- The manifest version matches the current Confluence version.
- The recorded PDF still exists.
- The recorded PDF is a valid PDF file.
- `--force` was not supplied.

For combined child downloads, the combined PDF is skipped only when every page in that
root's subtree is unchanged and all pages point to the same recorded PDF.

The single `download` command does not use the manifest as a version cache. It skips an
existing valid destination PDF unless `--force` is supplied.

## 🔎 Discover Pages and Generate Bulk Configs

Search for pages whose titles closely match a string:

```bash
uv run confluence-downloader search "architecture overview"
```

Restrict the search to one space:

```bash
uv run confluence-downloader search "architecture overview" --space DOC
```

Limit the number of returned matches:

```bash
uv run confluence-downloader search "architecture overview" --space DOC --limit 5
```

List a space page tree to a chosen depth. Root pages are depth 1:

```bash
uv run confluence-downloader list-space --space DOC --depth 2
```

List below a specific page title instead of the whole space:

```bash
uv run confluence-downloader list-space \
  --space DOC \
  --root-title "Architecture" \
  --depth 2
```

Create or update a bulk config from the pages at the final listed depth:

```bash
uv run confluence-downloader list-space \
  --space DOC \
  --depth 2 \
  --bulk-config pages.json
```

Generated entries default to `"include_children": true`, so those final-depth pages become
subtree roots for later bulk downloads. Use `--no-bulk-include-children` when you want the
generated config to download only the listed pages.

## 📈 Progress Logs

Bulk mode prints progress for each group, root title, page discovery step, download, skip,
and summary. Use verbosity to control how noisy it is:

```bash
uv run confluence-downloader bulk --config pages.json --verbosity verbose
```

| Verbosity | Best for                                                     |
| --------- | ------------------------------------------------------------ |
| `quiet`   | Automation where only summaries and errors matter            |
| `normal`  | Day-to-day bulk downloads                                    |
| `verbose` | Large page trees where you want child-page traversal details |

Summary output is shown in a box after each group so it is easy to scan in long runs.

## 🐢 Rate Limits and Large Spaces

If Confluence returns `429 Too Many Requests`, slow the run down and allow retries:

```bash
uv run confluence-downloader bulk \
  --config pages.json \
  --output-dir ./pdfs \
  --request-delay 0.25 \
  --retry-backoff 2 \
  --max-retries 5
```

`--request-delay` is the minimum delay between Confluence requests. `--retry-backoff` is
the initial exponential backoff delay for HTTP 429 responses. If Confluence returns
`Retry-After`, that value is used instead.

## 📁 Output Layout

Files are written under `<output-dir>/<space>/`:

```text
pdfs/
└── DOC/
    ├── 0001-123456-architecture-overview-combined.pdf
    ├── 0002-789012-adr-index-combined.pdf
    └── downloaded_pages.md
```

Filenames include the page ID to avoid collisions:

```text
0001-123456-architecture-overview.pdf
0001-123456-architecture-overview-combined.pdf
```

Each space output directory includes `downloaded_pages.md`, a Markdown table keyed by page
ID with:

- page title
- Confluence URL
- downloaded version
- version date
- local PDF filename

Rerunning the tool updates existing manifest rows instead of adding duplicates.

## 🛠 PDF Rendering Behavior

The tool first tries Confluence Data Center's native FlyingPDF export flow. If Confluence
returns a login or MFA page instead of PDF bytes, it falls back to rendering the page's
REST `body.export_view` HTML with WeasyPrint.

The fallback renderer is designed to preserve headings, tables, inline formatting, and
images that can be fetched through the configured PAT. Existing `.pdf` files that are
actually HTML are detected and replaced on the next run.

## 🧪 Development

Run tests with:

```bash
uv run pytest
```
