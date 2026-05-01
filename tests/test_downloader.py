from pathlib import Path

from confluence_pdf.downloader import PdfDownloader, build_pdf_filename
from confluence_pdf.models import Page


class FakeClient:
    def __init__(self) -> None:
        self.downloaded: list[tuple[str, Path]] = []

    def resolve_page_by_title(self, space_key: str, title: str) -> Page:
        return Page(id={"Root": "1", "Other": "2"}[title], title=title)

    def iter_descendants(self, root: Page) -> list[Page]:
        if root.id == "1":
            return [Page(id="3", title="Child"), Page(id="4", title="Grandchild")]
        return []

    def download_pdf(self, page: Page, destination: Path) -> None:
        self.downloaded.append((page.id, destination))
        destination.write_bytes(b"%PDF- fake")


def test_build_pdf_filename_includes_index_id_and_slug() -> None:
    assert build_pdf_filename(3, Page(id="123", title="My Page")) == "0003-123-my-page.pdf"


def test_downloader_downloads_roots_and_descendants(tmp_path: Path) -> None:
    fake_client = FakeClient()
    downloader = PdfDownloader(fake_client)  # type: ignore[arg-type]

    summary = downloader.download(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=True,
    )

    assert summary.pages_found == 3
    assert len(summary.exported) == 3
    assert [page_id for page_id, _ in fake_client.downloaded] == ["1", "3", "4"]
    assert summary.manifest_path == tmp_path / "DOC" / "downloaded_pages.md"
    assert "Root" in summary.manifest_path.read_text(encoding="utf-8")


def test_downloader_skips_existing_files(tmp_path: Path) -> None:
    existing = tmp_path / "DOC" / "0001-1-root.pdf"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"%PDF- already here")
    fake_client = FakeClient()
    downloader = PdfDownloader(fake_client)  # type: ignore[arg-type]

    summary = downloader.download(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=False,
    )

    assert summary.skipped == [existing]
    assert summary.exported == []
    assert fake_client.downloaded == []
    assert summary.manifest_path == tmp_path / "DOC" / "downloaded_pages.md"


def test_downloader_replaces_existing_non_pdf_file(tmp_path: Path) -> None:
    existing = tmp_path / "DOC" / "0001-1-root.pdf"
    existing.parent.mkdir(parents=True)
    existing.write_text("<!DOCTYPE html><h1>Login</h1>", encoding="utf-8")
    fake_client = FakeClient()
    downloader = PdfDownloader(fake_client)  # type: ignore[arg-type]

    summary = downloader.download(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=False,
    )

    assert summary.skipped == []
    assert summary.exported == [existing]
    assert existing.read_bytes() == b"%PDF- fake"


def test_downloader_force_replaces_existing_valid_pdf(tmp_path: Path) -> None:
    existing = tmp_path / "DOC" / "0001-1-root.pdf"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"%PDF- old")
    fake_client = FakeClient()
    downloader = PdfDownloader(fake_client)  # type: ignore[arg-type]

    summary = downloader.download(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=False,
        force=True,
    )

    assert summary.skipped == []
    assert summary.exported == [existing]
    assert existing.read_bytes() == b"%PDF- fake"
