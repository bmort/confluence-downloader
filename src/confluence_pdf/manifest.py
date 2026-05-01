from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import Page

MANIFEST_FILENAME = "downloaded_pages.md"
HEADER = "| Page ID | Title | URL | Version | Version Date | PDF |\n"
SEPARATOR = "| --- | --- | --- | --- | --- | --- |\n"


@dataclass(frozen=True)
class ManifestRecord:
    page: Page
    pdf_path: Path


def update_manifest(manifest_path: Path, records: list[ManifestRecord]) -> None:
    existing = _read_existing_records(manifest_path)
    for record in records:
        existing[record.page.id] = _record_to_row(record)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [existing[page_id] for page_id in sorted(existing, key=_sort_page_id)]
    manifest_path.write_text(HEADER + SEPARATOR + "".join(rows), encoding="utf-8")


def _read_existing_records(manifest_path: Path) -> dict[str, str]:
    if not manifest_path.exists():
        return {}

    records: dict[str, str] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines(keepends=True):
        if not line.startswith("| ") or line in {HEADER, SEPARATOR}:
            continue
        columns = [column.strip() for column in line.strip().strip("|").split("|")]
        if columns and columns[0] and columns[0] != "---":
            records[_unescape_markdown(columns[0])] = line
    return records


def _record_to_row(record: ManifestRecord) -> str:
    page = record.page
    pdf_name = record.pdf_path.name
    version = "" if page.version is None else str(page.version)
    return (
        f"| {_escape_markdown(page.id)} "
        f"| {_escape_markdown(page.title)} "
        f"| {_link(page.url)} "
        f"| {_escape_markdown(version)} "
        f"| {_escape_markdown(page.version_when)} "
        f"| {_escape_markdown(pdf_name)} |\n"
    )


def _link(url: str) -> str:
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
