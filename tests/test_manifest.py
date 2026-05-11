from pathlib import Path

from confluence_downloader.manifest import ManifestRecord, read_manifest_entries, update_manifest
from confluence_downloader.models import Page


def test_update_manifest_writes_download_metadata(tmp_path: Path) -> None:
    manifest = tmp_path / "downloaded_pages.md"
    update_manifest(
        manifest,
        [
            ManifestRecord(
                page=Page(
                    id="123",
                    title="Root | Page",
                    url="https://confluence.example.test/display/DOC/Root",
                    version=7,
                    version_when="2026-05-01T08:30:00.000Z",
                ),
                pdf_path=tmp_path / "root-123.pdf",
            )
        ],
    )

    assert manifest.read_text(encoding="utf-8") == (
        "| Page ID | Title | URL | Version | Version Date | PDF |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 123 | Root \\| Page | [https://confluence.example.test/display/DOC/Root](https://confluence.example.test/display/DOC/Root) | 7 | 2026-05-01T08:30:00.000Z | root-123.pdf |\n"
    )

    entries = read_manifest_entries(manifest)
    assert entries["123"].version == 7
    assert entries["123"].pdf_name == "root-123.pdf"


def test_update_manifest_replaces_existing_page_row(tmp_path: Path) -> None:
    manifest = tmp_path / "downloaded_pages.md"
    update_manifest(
        manifest,
        [
            ManifestRecord(
                page=Page(id="123", title="Old", url="https://old.example.test", version=1),
                pdf_path=Path("old.pdf"),
            )
        ],
    )
    update_manifest(
        manifest,
        [
            ManifestRecord(
                page=Page(id="123", title="New", url="https://new.example.test", version=2),
                pdf_path=Path("new.pdf"),
            )
        ],
    )

    content = manifest.read_text(encoding="utf-8")
    assert "Old" not in content
    assert "New" in content
    assert "new.pdf" in content
