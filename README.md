# Confluence PDF Context CLI

Download Confluence Data Center pages as individual PDFs for use as LLM context.

## Install

```bash
uv sync --dev
```

On macOS, the formatted fallback renderer requires WeasyPrint's native Pango
libraries:

```bash
brew install pango
```

## Usage

```bash
export CONFLUENCE_BASE_URL="https://confluence.example.com/confluence"
export CONFLUENCE_PAT="your-personal-access-token"

uv run confluence-pdf download \
  --space DOC \
  --title "Architecture Overview" \
  --include-children \
  --output-dir ./pdfs
```

Repeat `--title` to download multiple root pages, or pass a newline-delimited
file with `--titles-file`.

```bash
uv run confluence-pdf download --space DOC --titles-file titles.txt --output-dir ./pdfs
```

Use `--force` to regenerate existing valid PDFs, for example after upgrading
the fallback renderer:

```bash
uv run confluence-pdf download --space DOC --title "Architecture Overview" --output-dir ./pdfs --force
```

When using `--include-children`, the default is one combined PDF per requested
root containing the root page plus all descendants:

```bash
uv run confluence-pdf download \
  --space DOC \
  --title "Architecture Overview" \
  --include-children \
  --output-dir ./pdfs
```

Use `--separate-pages` to restore one PDF per page.

For bulk downloads across spaces, create a JSON config:

```json
{
  "include_children": true,
  "pages": [
    {"space": "DOC", "title": "Architecture Overview"},
    {"space": "OPS", "title": "Operations Runbook", "include_children": false}
  ]
}
```

Then run:

```bash
uv run confluence-pdf bulk --config pages.json --output-dir ./pdfs
```

Bulk mode uses each space's `downloaded_pages.md` manifest as a version cache.
It only downloads a page when Confluence reports a different version from the
last recorded download, unless `--force` is supplied.
By default, each configured page is processed as its own group, so progress is
easy to follow:

```bash
uv run confluence-pdf bulk --config pages.json --group-by-page
```

Use `--group-by-space` to combine pages that share the same space and
`include_children` setting into fewer downloader runs:

```bash
uv run confluence-pdf bulk --config pages.json --group-by-space
```

In bulk mode, config entries with `"include_children": true` also default to one
combined PDF per configured root. Use `--separate-pages` to write one PDF per
page instead.

Bulk mode prints emoji-prefixed progress logs for each group, each configured
root title, and per-page progress. Control the amount of progress output with
`--verbosity quiet`, `--verbosity normal`, or `--verbosity verbose`.
`normal` is the default for bulk mode.

```bash
uv run confluence-pdf bulk --config pages.json --verbosity verbose
```

`verbose` also logs each parent page checked while expanding child pages, how
many children were found there, and the descendant count discovered so far. This
is useful for large one-group runs created with `--group-by-space`.

For large spaces or rate-limited Confluence instances, slow requests down and
retry `429 Too Many Requests` responses:

```bash
uv run confluence-pdf bulk \
  --config pages.json \
  --output-dir ./pdfs \
  --request-delay 0.25 \
  --retry-backoff 2 \
  --max-retries 5
```

`--request-delay` is the minimum delay between Confluence requests.
`--retry-backoff` is the initial exponential backoff delay for HTTP 429
responses. If Confluence returns `Retry-After`, that value is used instead.

To discover pages in a space, list the page tree to a chosen depth. Root pages
are depth 1:

```bash
uv run confluence-pdf list-space --space DOC --depth 2
```

To list only below a specific page title in that space, pass `--root-title`.
The selected page becomes depth 1 for that listing:

```bash
uv run confluence-pdf list-space --space DOC --root-title "Architecture" --depth 2
```

To create or update a bulk config from the final listed depth, pass
`--bulk-config`. For example, this lists root pages and their direct children,
then writes only the depth-2 pages into `pages.json`:

```bash
uv run confluence-pdf list-space --space DOC --depth 2 --bulk-config pages.json
```

Generated entries default to `"include_children": true`, so later bulk downloads
use those final-depth pages as subtree roots. Use `--no-bulk-include-children`
to write entries that download only the listed pages.

Run tests with:

```bash
uv run pytest
```

The tool writes files under `<output-dir>/<space>/` using names such as:

```text
0001-123456-architecture-overview.pdf
```

Existing files are skipped.

Each space output directory also contains `downloaded_pages.md`, a Markdown
table keyed by page ID with the page title, Confluence URL, downloaded version,
version date, and local PDF filename. Rerunning the tool updates existing rows
instead of adding duplicates.

If Confluence's native PDF export action returns a login or MFA page instead of
PDF bytes, the tool falls back to rendering the page's REST `body.export_view`
HTML with WeasyPrint. This preserves page structure such as headings, tables,
inline formatting, and images that can be fetched through the configured PAT.
Existing `.pdf` files that are actually HTML are detected and replaced on the
next run.
