from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path

from .models import Page

MANIFEST_FILENAME = "downloaded_pages.md"
HTML_MANIFEST_FILENAME = "downloaded_pages.html"
HEADER = "| Page ID | Title | URL | Version | Version Date | PDF | HTML |\n"
SEPARATOR = "| --- | --- | --- | --- | --- | --- | --- |\n"
HTML_COLUMN_LABELS = ("Title", "Version", "Version Date", "Page ID", "Space")
HTML_STYLE = """
:root {
  color-scheme: light;
  --ink: #172026;
  --line: #cfd8df;
  --paper: #f8f6f1;
  --panel: #ffffff;
  --head: #24313a;
  --accent: #0f766e;
  --row: #eef6f4;
}
* {
  box-sizing: border-box;
}
body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: Georgia, 'Times New Roman', serif;
}
main {
  padding: clamp(1rem, 4vw, 3rem);
}
h1 {
  margin: 0 0 1rem;
  color: var(--head);
  font-size: clamp(1.75rem, 3vw, 3rem);
  font-weight: 700;
  line-height: 1;
}
.table-wrap {
  overflow-x: auto;
  border: 1px solid var(--line);
  background: var(--panel);
  box-shadow: 0 16px 40px rgba(23, 32, 38, 0.08);
}
table {
  border-collapse: collapse;
  min-width: 56rem;
  width: 100%;
}
th,
td {
  border-bottom: 1px solid var(--line);
  padding: 0.72rem 0.85rem;
  text-align: left;
  vertical-align: top;
}
th {
  position: sticky;
  top: 0;
  background: var(--head);
  color: #fff;
  font-family: Verdana, Geneva, sans-serif;
  font-size: 0.72rem;
  letter-spacing: 0;
  text-transform: uppercase;
}
td {
  font-size: 0.95rem;
  line-height: 1.35;
}
tbody tr:nth-child(even) {
  background: var(--row);
}
tbody tr:hover {
  background: #f3e8c9;
}
td:nth-child(2),
td:nth-child(4),
td:nth-child(5) {
  font-family: 'Courier New', monospace;
  white-space: nowrap;
}
td:nth-child(3) {
  white-space: nowrap;
}
a {
  color: var(--accent);
  font-weight: 700;
  text-decoration-thickness: 0.08em;
  text-underline-offset: 0.18em;
}
"""


@dataclass(frozen=True)
class ManifestRecord:
    page: Page
    pdf_path: Path
    html_path: Path | None = None


@dataclass(frozen=True)
class ManifestEntry:
    page_id: str
    version: int | None
    pdf_name: str
    html_name: str = ""


def update_manifest(manifest_path: Path, records: list[ManifestRecord]) -> None:
    existing = _read_existing_records(manifest_path)
    for record in records:
        existing[record.page.id] = _record_to_columns(record)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [existing[page_id] for page_id in sorted(existing, key=_sort_page_id)]
    manifest_path.write_text(
        HEADER + SEPARATOR + "".join(_columns_to_markdown_row(row) for row in rows),
        encoding="utf-8",
    )
    html_manifest_path = manifest_path.with_name(HTML_MANIFEST_FILENAME)
    html_manifest_path.write_text(_records_to_html_table(rows), encoding="utf-8")


def read_manifest_entries(manifest_path: Path) -> dict[str, ManifestEntry]:
    entries: dict[str, ManifestEntry] = {}
    for columns in _read_rows(manifest_path):
        if len(columns) < 6:
            continue
        page_id = _unescape_markdown(columns[0])
        entries[page_id] = ManifestEntry(
            page_id=page_id,
            version=_parse_version(columns[3]),
            pdf_name=_unescape_markdown(columns[5]),
            html_name=_unescape_markdown(columns[6]) if len(columns) > 6 else "",
        )
    return entries


def _read_existing_records(manifest_path: Path) -> dict[str, list[str]]:
    records: dict[str, list[str]] = {}
    for columns, line in _read_rows_with_lines(manifest_path):
        if columns:
            del line
            records[_unescape_markdown(columns[0])] = _markdown_columns_to_values(columns)
    return records


def _read_rows(manifest_path: Path) -> list[list[str]]:
    return [columns for columns, _ in _read_rows_with_lines(manifest_path)]


def _read_rows_with_lines(manifest_path: Path) -> list[tuple[list[str], str]]:
    if not manifest_path.exists():
        return []

    rows: list[tuple[list[str], str]] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines(keepends=True):
        if not line.startswith("| ") or _is_header_or_separator(line):
            continue
        columns = _split_markdown_row(line)
        if columns and columns[0] and columns[0] != "---":
            rows.append((columns, line))
    return rows


def _split_markdown_row(line: str) -> list[str]:
    content = line.strip().strip("|")
    columns: list[str] = []
    current: list[str] = []
    escaped = False
    for character in content:
        if escaped:
            current.append("\\" + character)
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == "|":
            columns.append("".join(current).strip())
            current = []
            continue
        current.append(character)
    columns.append("".join(current).strip())
    return columns


def _is_header_or_separator(line: str) -> bool:
    columns = [column.strip() for column in line.strip().strip("|").split("|")]
    return bool(columns) and columns[0] in {"Page ID", "---"}


def _parse_version(value: str) -> int | None:
    unescaped = _unescape_markdown(value)
    if unescaped.isdigit():
        return int(unescaped)
    return None


def _record_to_columns(record: ManifestRecord) -> list[str]:
    page = record.page
    pdf_name = record.pdf_path.name
    html_name = "" if record.html_path is None else _html_manifest_path(record)
    version = "" if page.version is None else str(page.version)
    return [
        page.id,
        page.title,
        page.url,
        version,
        page.version_when,
        pdf_name,
        html_name,
        page.space,
    ]


def _html_manifest_path(record: ManifestRecord) -> str:
    if record.html_path is None:
        return ""
    try:
        return record.html_path.relative_to(record.pdf_path.parent).as_posix()
    except ValueError:
        return record.html_path.name


def _markdown_columns_to_values(columns: list[str]) -> list[str]:
    values = [_unescape_markdown(column) for column in columns]
    if len(values) >= 3:
        values[2] = _unwrap_markdown_link(values[2])
    if len(values) == 6:
        values.append("")
    if len(values) == 7:
        values.append("")
    return values


def _unwrap_markdown_link(value: str) -> str:
    if not value.startswith("["):
        return value
    link_start = value.rfind("](")
    if link_start == -1 or not value.endswith(")"):
        return value
    return value[link_start + 2 : -1].replace("%20", " ").replace("%29", ")")


def _columns_to_markdown_row(columns: list[str]) -> str:
    page_id, title, url, version, version_when, pdf_name, html_name, *_space = columns
    return (
        f"| {_escape_markdown(page_id)} "
        f"| {_escape_markdown(title)} "
        f"| {_markdown_link(url)} "
        f"| {_escape_markdown(version)} "
        f"| {_escape_markdown(version_when)} "
        f"| {_escape_markdown(pdf_name)} "
        f"| {_escape_markdown(html_name)} |\n"
    )


def _records_to_html_table(rows: list[list[str]]) -> str:
    body = "".join(_columns_to_html_row(row) for row in rows)
    header = "".join(
        f"<th scope=\"col\">{escape(label)}</th>" for label in HTML_COLUMN_LABELS
    )
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Downloaded Pages</title>\n"
        "  <style>\n"
        f"{HTML_STYLE.rstrip()}\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <main>\n"
        "    <h1>Downloaded Pages</h1>\n"
        "    <div class=\"table-wrap\">\n"
        "      <table>\n"
        f"        <thead><tr>{header}</tr></thead>\n"
        f"        <tbody>\n{body}        </tbody>\n"
        "      </table>\n"
        "    </div>\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def _columns_to_html_row(columns: list[str]) -> str:
    page_id, title, url, version, version_when, _pdf_name, _html_name, space = columns
    title_cell = escape(title)
    if url:
        escaped_url = escape(url, quote=True)
        title_cell = f'<a href="{escaped_url}">{escape(title)}</a>'
    cells = [
        title_cell,
        escape(version),
        escape(version_when),
        escape(page_id),
        escape(space),
    ]
    return "          <tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>\n"


def _markdown_link(url: str) -> str:
    if not url:
        return ""
    escaped_url = url.replace(")", "%29").replace(" ", "%20")
    return f"[{_escape_markdown(url)}]({escaped_url})"


def _escape_markdown(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _unescape_markdown(value: str) -> str:
    return value.replace("\\|", "|").replace("\\\\", "\\")


def _sort_page_id(page_id: str) -> tuple[int, str]:
    if page_id.isdigit():
        return (0, f"{int(page_id):020d}")
    return (1, page_id)
