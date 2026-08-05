from pathlib import Path

from confluence_downloader.downloader import (
    PdfDownloader,
    build_attachments_destination,
    build_html_destination,
    build_html_filename,
    build_pdf_filename,
)
from confluence_downloader.models import Attachment, Page


class FakeClient:
    def __init__(self) -> None:
        self.downloaded: list[tuple[str, Path]] = []
        self.downloaded_html: list[tuple[str, Path]] = []
        self.downloaded_attachments: list[tuple[str, Path]] = []
        self.attachments: dict[str, list[Attachment]] = {}
        self.html_attachment_targets: dict[str, str] | None = None

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

    def download_html(
        self,
        page: Page,
        destination: Path,
        *,
        attachment_targets: dict[str, str] | None = None,
    ) -> None:
        self.downloaded_html.append((page.id, destination))
        self.html_attachment_targets = attachment_targets
        destination.write_text(f"<html><body>{page.title}</body></html>", encoding="utf-8")

    def list_attachments(self, page_id: str) -> list[Attachment]:
        return self.attachments.get(page_id, [])

    def download_attachment(self, attachment: Attachment, destination: Path) -> None:
        self.downloaded_attachments.append((attachment.id, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"attachment bytes")


def test_download_logs_link_page_titles_to_their_url(tmp_path: Path) -> None:
    fake_client = FakeClient()

    def resolve_with_url(space_key: str, title: str) -> Page:
        return Page(id="1", title=title, version=5, url="https://example.test/pages/1")

    fake_client.resolve_page_by_title = resolve_with_url  # type: ignore[method-assign]
    logs: list[str] = []
    downloader = PdfDownloader(fake_client, logger=lambda level, message: logs.append(message))  # type: ignore[arg-type]

    downloader.download(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=False,
    )

    linked_title = "\x1b]8;;https://example.test/pages/1\x1b\\Root\x1b]8;;\x1b\\"
    assert any(message.startswith(f"resolved: {linked_title} ") for message in logs)
    assert any(message.startswith(f"[1/1] {linked_title} ") for message in logs)


def test_build_pdf_filename_places_version_after_id() -> None:
    assert build_pdf_filename(Page(id="123", title="My Page", version=7)) == "my-page-123-v7.pdf"


def test_build_pdf_filename_omits_unknown_version() -> None:
    assert build_pdf_filename(Page(id="123", title="My Page")) == "my-page-123.pdf"


def test_build_html_filename_matches_pdf_stem() -> None:
    assert build_html_filename(Page(id="123", title="My Page", version=7)) == "my-page-123-v7.html"


def test_build_html_destination_uses_html_subdirectory(tmp_path: Path) -> None:
    assert build_html_destination(tmp_path, Page(id="123", title="My Page", version=7)) == (
        tmp_path / "html" / "my-page-123-v7.html"
    )


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
    assert fake_client.downloaded_html == []
    assert not (tmp_path / "html" / "root-1-v5.html").exists()
    assert summary.manifest_path == tmp_path / "downloaded_pages.md"
    assert summary.html_manifest_path == tmp_path / "downloaded_pages.html"
    assert "Root" in summary.manifest_path.read_text(encoding="utf-8")
    assert "Root" in summary.html_manifest_path.read_text(encoding="utf-8")
    messages = [message for _, message in logs]
    assert "Resolving root 1/1: Root" in messages
    assert "found 2 descendants" in messages
    assert any("checking children of Root" in message for message in messages)
    assert any("descendants discovered so far" in message for message in messages)
    assert any("[1/3] Root" in message for message in messages)
    assert any(level == "verbose" for level, _ in logs)


def test_downloader_skips_existing_files(tmp_path: Path) -> None:
    existing = tmp_path / "root-1-v5.pdf"
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
    assert fake_client.downloaded_html == []
    assert summary.manifest_path == tmp_path / "downloaded_pages.md"
    assert summary.html_manifest_path == tmp_path / "downloaded_pages.html"


def test_downloader_replaces_existing_non_pdf_file(tmp_path: Path) -> None:
    existing = tmp_path / "root-1-v5.pdf"
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
    existing = tmp_path / "root-1-v5.pdf"
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
    existing = tmp_path / "root-1-v5.pdf"
    existing.write_bytes(b"%PDF- already here")
    manifest = tmp_path / "downloaded_pages.md"
    manifest.write_text(
        "| Page ID | Title | URL | Version | Version Date | PDF |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 1 | Root |  | 5 |  | root-1-v5.pdf |\n",
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
    assert fake_client.downloaded_html == []


def test_downloader_skips_unchanged_version_from_filename_without_manifest(tmp_path: Path) -> None:
    existing = tmp_path / "root-1-v5.pdf"
    existing.write_bytes(b"%PDF- already here")
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


def test_downloader_downloads_changed_version_despite_existing_old_pdf(tmp_path: Path) -> None:
    old_pdf = tmp_path / "root-1-v4.pdf"
    old_pdf.write_bytes(b"%PDF- old")
    fake_client = FakeClient()
    downloader = PdfDownloader(fake_client)  # type: ignore[arg-type]

    summary = downloader.download(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=False,
        skip_unchanged=True,
    )

    new_pdf = tmp_path / "root-1-v5.pdf"
    assert summary.exported == [new_pdf]
    assert summary.skipped == []
    assert fake_client.downloaded == [("1", new_pdf)]
    assert fake_client.downloaded_html == []


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
    assert fake_client.downloaded_html == []
    manifest = (tmp_path / "downloaded_pages.md").read_text(encoding="utf-8")
    assert "root-combined-1.pdf" in manifest
    assert "html/root-1-v5.html" not in manifest


def test_downloader_stops_between_pages_when_should_stop_fires(tmp_path: Path) -> None:
    fake_client = FakeClient()
    downloader = PdfDownloader(
        fake_client,  # type: ignore[arg-type]
        should_stop=lambda: len(fake_client.downloaded) >= 1,
    )

    summary = downloader.download(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=True,
    )

    assert summary.cancelled
    assert [page_id for page_id, _ in fake_client.downloaded] == ["1"]
    assert len(summary.exported) == 1
    # Completed pages still land in the manifest.
    assert "Root" in (tmp_path / "downloaded_pages.md").read_text(encoding="utf-8")


def test_downloader_stops_between_combined_roots_when_should_stop_fires(tmp_path: Path) -> None:
    fake_client = FakeClient()
    downloader = PdfDownloader(
        fake_client,  # type: ignore[arg-type]
        should_stop=lambda: len(fake_client.downloaded) >= 1,
    )

    summary = downloader.download(
        space_key="DOC",
        titles=["Root", "Other"],
        output_dir=tmp_path,
        include_children=True,
        combine_children=True,
    )

    assert summary.cancelled
    assert summary.exported == [tmp_path / "root-combined-1.pdf"]


def test_downloader_can_optionally_download_html_pages(tmp_path: Path) -> None:
    fake_client = FakeClient()
    downloader = PdfDownloader(fake_client)  # type: ignore[arg-type]

    summary = downloader.download(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=True,
        download_html=True,
    )

    assert summary.pages_found == 3
    assert [page_id for page_id, _ in fake_client.downloaded_html] == ["1", "3", "4"]
    assert (tmp_path / "html" / "root-1-v5.html").exists()
    manifest = (tmp_path / "downloaded_pages.md").read_text(encoding="utf-8")
    assert "html/root-1-v5.html" in manifest


def test_downloader_can_optionally_download_combined_root_html_pages(tmp_path: Path) -> None:
    fake_client = FakeClient()
    downloader = PdfDownloader(fake_client)  # type: ignore[arg-type]

    summary = downloader.download(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=True,
        combine_children=True,
        download_html=True,
    )

    assert summary.exported == [tmp_path / "root-combined-1.pdf"]
    assert [page_id for page_id, _ in fake_client.downloaded_html] == ["1", "3", "4"]
    manifest = (tmp_path / "downloaded_pages.md").read_text(encoding="utf-8")
    assert "html/root-1-v5.html" in manifest


def test_downloader_can_optionally_download_attachments(tmp_path: Path) -> None:
    fake_client = FakeClient()
    fake_client.attachments["1"] = [
        Attachment(
            id="a1",
            title="meeting notes.txt",
            media_type="text/plain",
            file_size=10,
            version=3,
            download_path="/download/attachments/1/meeting%20notes.txt",
        ),
    ]
    downloader = PdfDownloader(fake_client)  # type: ignore[arg-type]

    downloader.download(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=False,
        download_html=True,
        download_attachments=True,
    )

    saved = tmp_path / "attachments" / "root-1" / "meeting notes.txt"
    assert saved.read_bytes() == b"attachment bytes"
    assert fake_client.html_attachment_targets == {
        "meeting notes.txt": "../attachments/root-1/meeting%20notes.txt"
    }
    manifest = (tmp_path / "downloaded_pages.md").read_text(encoding="utf-8")
    assert "meeting notes.txt@v3" in manifest


def test_downloader_skips_unchanged_attachments_on_rerun(tmp_path: Path) -> None:
    fake_client = FakeClient()
    fake_client.attachments["1"] = [
        Attachment(
            id="a1",
            title="notes.txt",
            version=3,
            download_path="/download/attachments/1/notes.txt",
        ),
    ]
    downloader = PdfDownloader(fake_client)  # type: ignore[arg-type]
    common = dict(
        space_key="DOC",
        titles=["Root"],
        output_dir=tmp_path,
        include_children=False,
        download_attachments=True,
    )

    downloader.download(**common)
    assert len(fake_client.downloaded_attachments) == 1

    downloader.download(**common)
    assert len(fake_client.downloaded_attachments) == 1

    fake_client.attachments["1"] = [
        Attachment(
            id="a1",
            title="notes.txt",
            version=4,
            download_path="/download/attachments/1/notes.txt",
        ),
    ]
    downloader.download(**common)
    assert len(fake_client.downloaded_attachments) == 2


def test_downloader_attachments_dirname_helpers(tmp_path: Path) -> None:
    page = Page(id="9", title="My Page!", version=1)
    assert build_attachments_destination(tmp_path, page) == tmp_path / "attachments" / "my-page-9"
