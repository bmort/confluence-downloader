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
