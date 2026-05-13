<p align="center">
  <img src="assets/confluence-downloader-logo.png" alt="Confluence Downloader CLI logo" width="400">
</p>

# Confluence Downloader

Turn Confluence Data Center pages into clean PDF context packs for LLM workflows.
The CLI can download one page, many named pages, or whole page trees; combine each page
tree into a single PDF by default; optionally write one HTML copy per Confluence page;
generate bulk download configs from a space tree; and skip unchanged pages in bulk and
prompted-download flows by comparing Confluence versions with the local manifest.

## ✨ What It Does

| Need                                                | Use                                                           |
| --------------------------------------------------- | ------------------------------------------------------------- |
| Download one page                                   | `confluence-downloader download --space KEY --title "Page"`          |
| Download a page and all descendants                 | Add `--include-children`                                      |
| Get one PDF per page instead of a combined tree PDF | Add `--separate-pages`                                        |
| Keep an HTML copy close to the Confluence view      | Add `--download-html`                                         |
| Download pages across multiple spaces               | Use `confluence-downloader bulk --config pages.json`                 |
| Skip pages already downloaded at the same version   | Use bulk or `--ask-download`, which read `downloaded_pages.md` |
| Discover pages and build a bulk config              | Use `confluence-downloader list --bulk-config pages.json`            |
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

Install the CLI from the checkout:

```bash
uv tool install --force .
```

This makes `confluence-downloader` available on your user PATH. If `uv` warns that
the tool directory is not on PATH, add the suggested directory to your shell profile
and restart your shell.

When reinstalling after local code changes, install the checkout in editable mode so
the command uses the current source tree:

```bash
uv tool install --force --editable .
```

If your shell still runs an older command after reinstalling, clear the shell command
cache or start a new shell:

```bash
rehash
```

For development, install the project and test dependencies into the local virtual
environment instead:

```bash
uv sync --dev
```

On macOS, the formatted fallback renderer requires WeasyPrint's native Pango libraries:

```bash
brew install pango
```

Check the CLI is available:

```bash
confluence-downloader --help
```

When working from the development environment, run the CLI with `uv run`:

```bash
uv run confluence-downloader --help
```

## 🤖 Agent Skill

This repository includes an agent skill for Codex and Claude Code to support
Confluence page review. See
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

| Option               | Short      | Applies to                        | Default                                       | Meaning                                                                           |
| -------------------- | ---------- | --------------------------------- | --------------------------------------------- | --------------------------------------------------------------------------------- |
| `--space`            | `-s`       | `download`, `list`, `search`       | Required for `download` and `list`            | Confluence space key, or search space filter                                      |
| `--title`            | `-t`       | `download`                        | Required unless `--titles-file` is used       | Confluence page title; repeat for multiple pages                                  |
| `--titles-file`      | `-T`       | `download`                        | Required unless `--title` is used             | Newline-delimited page titles                                                     |
| `--config`           | `-c`       | `bulk`                            | Required                                      | JSON bulk download configuration                                                  |
| `--include-children` | `-i`       | `download`, `bulk` config entries | Off for `download`; configurable in bulk JSON | Include all descendants, not only direct children                                 |
| `--combine-children` | `-c`, `-C` | `download`, `bulk`                | On                                            | Write one combined PDF per requested root when children are included              |
| `--separate-pages`   | `-p`       | `download`, `bulk`                | Off                                           | Write one PDF per page instead of one combined tree PDF                           |
| `--force`            | `-f`       | `download`, `bulk`, prompted downloads | Off                                      | Regenerate even when an existing PDF or manifest version would normally skip work |
| `--download-html`    |            | `download`, `bulk`, prompted downloads | Off                                      | Also write one standalone HTML copy per Confluence page under `html/`             |
| `--output-dir`       | `-o`       | `download`, `bulk`, prompted downloads | Current directory                        | Directory where PDFs, optional HTML copies, and manifests are written             |
| `--ask-download`     | `-a`       | `list`, `search`                  | Off                                           | Prompt to download the listed or matched pages after showing results              |
| `--yes`              | `-y`       | `list`, `search` with `--ask-download` | Off                                      | Auto-confirm prompted downloads                                                   |
| `--verbosity`        | `-v`       | `download`, `bulk`, prompted downloads | `normal`                                 | Choose `quiet`, `normal`, or `verbose`; prompted downloads use at least `normal`  |
| `--base-url`         | `-b`       | all commands                      | `CONFLUENCE_BASE_URL`                         | Confluence base URL                                                               |
| `--token`            | `-k`       | all commands                      | `CONFLUENCE_PAT`                              | Confluence Personal Access Token                                                  |

Other command-specific short aliases are shown in `--help`: `-d`, `-r`, and `-m`
cover request delay, retry backoff, and max retries where available; `list`
uses `-d` for `--depth`, `-r` for `--root-title`, `-c` for `--bulk-config`,
`-i/-I` for bulk config include-children, and `-D/-R` for request delay/retry
backoff. `bulk` uses `-g/-G` for grouping mode.

## 📚 Bulk Downloads

Use bulk mode when you have a repeatable set of pages, especially across spaces:

```json
{
  "output_dir": "./pdfs",
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
- Top-level `"output_dir"` is used by `bulk` when `--output-dir` is not supplied.
- A page entry can override that default with its own `"include_children"` value.
- `--group-by-page` is the default, so each configured page is processed as its own
  progress group.
- `--group-by-space` combines compatible entries into fewer downloader runs.

```bash
uv run confluence-downloader bulk --config pages.json --group-by-space
```

## ✅ Version-Aware Skipping

Bulk mode and `list`/`search` prompted downloads use each space's
`downloaded_pages.md` manifest as a version cache. Before downloading a page, the tool
resolves the current Confluence version and compares it with the manifest row for that
page ID. Versioned filenames are also checked as a fallback when the manifest is missing
or stale.

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

Prompt to download the returned matches:

```bash
uv run confluence-downloader search "architecture overview" --space DOC -a --output-dir ./pdfs
```

Add `--yes` or `-y` to auto-confirm the prompted download.

Prompted downloads always show at least `normal` progress logs, even if `--verbosity quiet`
is supplied.

Create or update a bulk config from the returned matches:

```bash
uv run confluence-downloader search "architecture overview" --space DOC --bulk-config pages.json
```

When `--ask-download` is accepted while writing `--bulk-config`, the prompted
`--output-dir` is stored in the generated bulk config. Later `bulk --config pages.json`
runs will use that folder unless `--output-dir` is supplied again.
When `--output-dir` is supplied while writing a relative `--bulk-config`, the config file
itself is written inside that output directory.

List a space page tree to a chosen depth. Root pages are depth 1:

```bash
uv run confluence-downloader list --space DOC --depth 2
```

List below a specific page title instead of the whole space:

```bash
uv run confluence-downloader list \
  --space DOC \
  --root-title "Architecture" \
  --depth 2
```

Create or update a bulk config from the pages at the final listed depth:

```bash
uv run confluence-downloader list \
  --space DOC \
  --depth 2 \
  --output-dir ./pdfs \
  --bulk-config pages.json
```

Prompt to download every listed page:

```bash
uv run confluence-downloader list --space DOC --depth 2 -a --output-dir ./pdfs
```

Add `--yes` or `-y` to auto-confirm that prompted download.

If `--output-dir` is provided while writing a relative `--bulk-config`, the config file
is written inside that output directory.

Generated entries default to `"include_children": true`, so those final-depth pages become
subtree roots for later bulk downloads. Use `--no-bulk-include-children` when you want the
generated config to download only the listed pages.

## 📈 Progress Logs

Download and bulk modes print progress for each root title, page discovery step, download,
skip, and summary. Use verbosity to control how noisy it is:

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

Files are written directly into the current directory by default, or directly into
the directory specified by `--output-dir`. The space key is not added to the output
path.

```text
.
├── architecture-overview-combined-123456.pdf
├── adr-index-combined-789012.pdf
├── downloaded_pages.html
└── downloaded_pages.md
```

Filenames use the slugified page title, then the page ID, to avoid collisions. If
`--download-html` is supplied, page HTML copies are written under `html/`:

```text
architecture-overview-123456-v7.pdf
html/architecture-overview-123456-v7.html
architecture-overview-combined-123456.pdf
```

The output directory includes `downloaded_pages.md`, a Markdown table keyed by page ID,
and `downloaded_pages.html`, a browser-friendly table with the same rows. The manifest
tables include:

- page title
- Confluence URL
- downloaded version
- version date
- local PDF filename
- local HTML filename, when `--download-html` was used

Rerunning the tool updates existing manifest rows instead of adding duplicates.

## 🛠 PDF and HTML Rendering Behavior

The tool first tries Confluence Data Center's native FlyingPDF export flow. If Confluence
returns a login or MFA page instead of PDF bytes, it falls back to rendering the page's
REST `body.export_view` HTML with WeasyPrint.

The fallback renderer is designed to preserve headings, tables, inline formatting, and
images that can be fetched through the configured PAT. Existing `.pdf` files that are
actually HTML are detected and replaced on the next run.

When `--download-html` is used, the `.html` copy writes Confluence REST
`body.styled_view` when available, falling back to `body.export_view`. The file includes
a `<base>` tag for the configured Confluence URL so relative image and attachment links
resolve as closely as possible to the original page when opened in a browser with access
to Confluence.

## 🧪 Development

Run tests with:

```bash
uv run pytest
```
