from pathlib import Path

from confluence_downloader.manifest import ManifestRecord, read_manifest_entries, update_manifest
from confluence_downloader.models import Page


def test_update_manifest_writes_download_metadata(tmp_path: Path) -> None:
    manifest = tmp_path / "downloaded_pages.md"
    html_manifest = tmp_path / "downloaded_pages.html"
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
                    space="DOC",
                ),
                pdf_path=tmp_path / "root-123.pdf",
                html_path=tmp_path / "html" / "root-123.html",
            )
        ],
    )

    assert manifest.read_text(encoding="utf-8") == (
        "| Page ID | Title | URL | Version | Version Date | PDF | HTML |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| 123 | Root \\| Page | [https://confluence.example.test/display/DOC/Root](https://confluence.example.test/display/DOC/Root) | 7 | 2026-05-01T08:30:00.000Z | root-123.pdf | html/root-123.html |\n"
    )

    entries = read_manifest_entries(manifest)
    assert entries["123"].version == 7
    assert entries["123"].pdf_name == "root-123.pdf"
    assert entries["123"].html_name == "html/root-123.html"

    html = html_manifest.read_text(encoding="utf-8")
    assert "<title>Downloaded Pages</title>" in html
    assert '<th scope="col">Title</th>' in html
    assert '<th scope="col">URL</th>' not in html
    assert '<th scope="col">PDF</th>' not in html
    assert '<th scope="col">HTML</th>' not in html
    assert (
        '<td><a href="https://confluence.example.test/display/DOC/Root">Root | Page</a></td>'
    ) in html
    assert "<td>7</td>" in html
    assert "<td>2026-05-01T08:30:00.000Z</td>" in html
    assert "<td>123</td>" in html
    assert "<td>DOC</td>" in html
    assert "root-123.pdf" not in html
    assert "html/root-123.html" not in html


def test_read_manifest_entries_accepts_legacy_manifest_without_html_column(tmp_path: Path) -> None:
    manifest = tmp_path / "downloaded_pages.md"
    manifest.write_text(
        "| Page ID | Title | URL | Version | Version Date | PDF |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 123 | Root |  | 7 |  | root-123.pdf |\n",
        encoding="utf-8",
    )

    entries = read_manifest_entries(manifest)

    assert entries["123"].pdf_name == "root-123.pdf"
    assert entries["123"].html_name == ""


def test_update_manifest_replaces_existing_page_row(tmp_path: Path) -> None:
    manifest = tmp_path / "downloaded_pages.md"
    html_manifest = tmp_path / "downloaded_pages.html"
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

    html = html_manifest.read_text(encoding="utf-8")
    assert "Old" not in html
    assert "New" in html
    assert "new.pdf" not in html


def test_update_manifest_preserves_existing_rows_in_html_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "downloaded_pages.md"
    update_manifest(
        manifest,
        [
            ManifestRecord(
                page=Page(id="123", title="Root", url="https://example.test/root", version=1),
                pdf_path=Path("root.pdf"),
            )
        ],
    )
    update_manifest(
        manifest,
        [
            ManifestRecord(
                page=Page(id="456", title="Leaf", url="https://example.test/leaf", version=2),
                pdf_path=Path("leaf.pdf"),
            )
        ],
    )

    html = (tmp_path / "downloaded_pages.html").read_text(encoding="utf-8")
    assert '<a href="https://example.test/root">Root</a>' in html
    assert '<a href="https://example.test/leaf">Leaf</a>' in html


def test_update_manifest_escapes_html_manifest_values(tmp_path: Path) -> None:
    manifest = tmp_path / "downloaded_pages.md"
    update_manifest(
        manifest,
        [
            ManifestRecord(
                page=Page(
                    id="123",
                    title='Root <script>alert("bad")</script>',
                    url="https://example.test/root?a=1&b=2",
                    version=1,
                    space="<DOC>",
                ),
                pdf_path=Path('root-"unsafe".pdf'),
            )
        ],
    )

    html = (tmp_path / "downloaded_pages.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(&quot;bad&quot;)&lt;/script&gt;" in html
    assert 'href="https://example.test/root?a=1&amp;b=2"' in html
    assert "&lt;DOC&gt;" in html
    assert "root-&quot;unsafe&quot;.pdf" not in html
