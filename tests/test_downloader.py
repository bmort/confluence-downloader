from pathlib import Path

from confluence_downloader.downloader import PdfDownloader, build_pdf_filename
from confluence_downloader.models import Page


class FakeClient:
    def __init__(self) -> None:
        self.downloaded: list[tuple[str, Path]] = []

    def resolve_page_by_title(self, space_key: str, title: str) -> Page:
        return Page(id={"Root": "1", "Other": "2"}[title], title=title, version=5)

    def iter_descendants(self, root: Page) -> list[Page]:
        if root.id == "1":
            return [
                Page(id="3", title="Child", version=2),
                Page(id="4", title="Grandchild", version=1),
            ]
        return []

    def list_child_pages(self, page_id: str) -> list[Page]:
        return {
            "1": [
                Page(id="3", title="Child", version=2),
                Page(id="4", title="Grandchild", version=1),
            ],
            "3": [],
            "4": [],
        }[page_id]

    def download_pdf(self, page: Page, destination: Path) -> None:
        self.downloaded.append((page.id, destination))
        destination.write_bytes(b"%PDF- fake")

    def download_combined_pdf(self, pages: list[Page], destination: Path) -> None:
        self.downloaded.append(("+".join(page.id for page in pages), destination))
        destination.write_bytes(b"%PDF- combined")


def test_build_pdf_filename_places_id_at_end() -> None:
    assert build_pdf_filename(Page(id="123", title="My Page")) == "my-page-123.pdf"


def test_downloader_downloads_roots_and_descendants(tmp_path: Path) -> None:
    fake_client = FakeClient()
    logs = []
    downloader = PdfDownloader(fake_client, logger=lambda level, message: logs.append((level, message)))  # type: ignore[arg-type]

    summary = downloader.download(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=True,
    )

    assert summary.pages_found == 3
    assert len(summary.exported) == 3
    assert [page_id for page_id, _ in fake_client.downloaded] == ["1", "3", "4"]
    assert summary.manifest_path == tmp_path / "downloaded_pages.md"
    assert "Root" in summary.manifest_path.read_text(encoding="utf-8")
    messages = [message for _, message in logs]
    assert "Resolving root 1/1: Root" in messages
    assert "found 2 descendants" in messages
    assert any("checking children of Root" in message for message in messages)
    assert any("descendants discovered so far" in message for message in messages)
    assert any("[1/3] Root" in message for message in messages)
    assert any(level == "verbose" for level, _ in logs)


def test_downloader_skips_existing_files(tmp_path: Path) -> None:
    existing = tmp_path / "root-1.pdf"
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
    assert summary.manifest_path == tmp_path / "downloaded_pages.md"


def test_downloader_replaces_existing_non_pdf_file(tmp_path: Path) -> None:
    existing = tmp_path / "root-1.pdf"
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
    existing = tmp_path / "root-1.pdf"
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


def test_downloader_bulk_skips_unchanged_manifest_version(tmp_path: Path) -> None:
    existing = tmp_path / "root-1.pdf"
    existing.write_bytes(b"%PDF- already here")
    manifest = tmp_path / "downloaded_pages.md"
    manifest.write_text(
        "| Page ID | Title | URL | Version | Version Date | PDF |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 1 | Root |  | 5 |  | root-1.pdf |\n",
        encoding="utf-8",
    )
    fake_client = FakeClient()
    downloader = PdfDownloader(fake_client)  # type: ignore[arg-type]

    summary = downloader.download(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=False,
        skip_unchanged=True,
    )

    assert summary.skipped_unchanged == [existing]
    assert summary.exported == []
    assert fake_client.downloaded == []


def test_downloader_can_combine_children_into_single_pdf(tmp_path: Path) -> None:
    fake_client = FakeClient()
    downloader = PdfDownloader(fake_client)  # type: ignore[arg-type]

    summary = downloader.download(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=True,
        combine_children=True,
    )

    output = tmp_path / "root-combined-1.pdf"
    assert summary.pages_found == 3
    assert summary.exported == [output]
    assert fake_client.downloaded == [("1+3+4", output)]
    manifest = (tmp_path / "downloaded_pages.md").read_text(encoding="utf-8")
    assert "root-combined-1.pdf" in manifest
