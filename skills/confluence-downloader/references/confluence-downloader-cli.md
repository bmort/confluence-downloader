# Confluence Downloader CLI Reference

## Location

Default repository: the current working directory. Run the helper from the `confluence-downloader` repository root, or pass `--repo /path/to/confluence-downloader`.

Command prefix on macOS:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run confluence-downloader ...
```

The library path is needed for WeasyPrint fallback PDF rendering.

## Authentication

The CLI reads:

- `CONFLUENCE_BASE_URL`
- `CONFLUENCE_PAT`

Equivalent flags are `--base-url` and `--token`. Avoid echoing tokens in final responses.

## Bulk Config

Bulk mode is the preferred repeatable mode because it uses `downloaded_pages.md` to skip pages whose Confluence version is unchanged.

```json
{
  "include_children": true,
  "pages": [
    { "space": "DOC", "title": "Architecture Overview" },
    { "space": "OPS", "title": "Operations Runbook", "include_children": false }
  ]
}
```

Run:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run confluence-downloader bulk --config pages.json --output-dir ./pdfs --verbosity normal
```

Useful flags:

- `--force`: regenerate even when unchanged; use only when requested.
- `--group-by-page`: default; processes each config page separately.
- `--group-by-space`: combines compatible entries by space.
- `--separate-pages`: write one PDF per page instead of a combined child tree PDF.
- `--request-delay`, `--retry-backoff`, `--max-retries`: use for rate limits or large spaces.

By default, downloads write PDFs plus manifests. Add `--download-html` to also write a
close-to-original `.html` copy under `html/` for each Confluence page.

## Direct Download

Use direct download for small ad hoc requests:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run confluence-downloader download --space DOC --title "Page" --output-dir ./pdfs
```

Repeat `--title` for multiple titles. Add `--include-children` to fetch descendants. By default, child trees are combined into one PDF per root; add `--separate-pages` to get individual PDFs. Add `--download-html` to write one HTML copy per page.

Direct download skips an existing valid destination PDF unless `--force` is used, but it does not do version-aware manifest skipping like bulk mode.

## Discovery

Use `search` when the user has an approximate page title:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run confluence-downloader search "architecture overview"
```

Restrict matching to one space:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run confluence-downloader search "architecture overview" --space DOC --limit 5
```

Search output is a table with Page ID, Space, Title, and URL. Use the exact returned title
when calling `download` or creating a bulk config.

Add `--ask-download` or `-a` with `--output-dir ./pdfs` to prompt for downloading all
returned matches after the search table is printed. Prompted downloads always use at
least `normal` progress verbosity, even if `--verbosity quiet` is supplied.
Add `--yes` or `-y` to auto-confirm that prompted download.

Add `--bulk-config pages.json` to create or update a bulk config from the returned
matches. Use `--bulk-include-children` when the generated entries should pull page
subtrees later.

When `--ask-download` is accepted while writing `--bulk-config`, the prompted
`--output-dir` is stored as top-level `output_dir` in that config. Future
`bulk --config pages.json` runs use it unless `--output-dir` is supplied explicitly.
When `--output-dir` is supplied while writing a relative `--bulk-config`, the config file
itself is written inside that output directory.

Use `list` when the user describes a space or subtree but not exact page titles:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run confluence-downloader list --space DOC --depth 2
```

Create or update a bulk config from final-depth pages:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run confluence-downloader list --space DOC --depth 2 --bulk-config pages.json
```

Add `--root-title "Title"` to start below a page. Use `--no-bulk-include-children` when generated config entries should download only those listed pages.

Add `--ask-download` or `-a` with `--output-dir ./pdfs` to prompt for downloading every
listed page after the tree is printed.
Add `--yes` or `-y` to auto-confirm that prompted download.
When writing a relative `--bulk-config`, pass `--output-dir` to place the generated file
inside that output directory.

`list` output quotes titles and separates metadata with `|`, for example:

```text
- "Architecture [draft]" | id=123 version=7
  - "Child Page" | id=456 version=2
```

Treat the text inside double quotes as the page title. The `id=` and `version=` fields are
metadata, not part of the title.

## Output Layout

PDF files are written directly under `<output-dir>`. When `--download-html` is used,
page HTML copies are written under `<output-dir>/html/`. The output directory may
contain `downloaded_pages.md`, a Markdown manifest table with Page ID, Title, URL,
Version, Version Date, PDF filename, and optional HTML path. It may also contain
`downloaded_pages.html`, a browser-friendly table generated from the same rows.

Filenames use the slugified page title, then the page ID, and combined trees add
`-combined` before the page ID.
