from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .client import ConfluenceClient
from .errors import PdfExportError
from .manifest import MANIFEST_FILENAME, ManifestRecord, update_manifest
from .models import Page
from .render import is_pdf_file
from .utils import slugify_title


@dataclass
class DownloadFailure:
    page: Page
    error: str


@dataclass
class DownloadSummary:
    roots_requested: int = 0
    pages_found: int = 0
    exported: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    failures: list[DownloadFailure] = field(default_factory=list)
    manifest_path: Path | None = None

    @property
    def failed(self) -> int:
        return len(self.failures)


class PdfDownloader:
    def __init__(self, client: ConfluenceClient) -> None:
        self.client = client

    def download(
        self,
        *,
        space_key: str,
        titles: list[str],
        output_dir: Path,
        include_children: bool,
        force: bool = False,
    ) -> DownloadSummary:
        summary = DownloadSummary(roots_requested=len(titles))
        output_space_dir = output_dir / space_key
        output_space_dir.mkdir(parents=True, exist_ok=True)

        pages = self._collect_pages(space_key, titles, include_children)
        summary.pages_found = len(pages)
        manifest_records: list[ManifestRecord] = []

        for index, page in enumerate(pages, start=1):
            destination = output_space_dir / build_pdf_filename(index, page)
            if not force and destination.exists() and is_pdf_file(destination):
                summary.skipped.append(destination)
                manifest_records.append(ManifestRecord(page=page, pdf_path=destination))
                continue
            try:
                self.client.download_pdf(page, destination)
            except PdfExportError as exc:
                summary.failures.append(DownloadFailure(page=page, error=str(exc)))
                continue
            summary.exported.append(destination)
            manifest_records.append(ManifestRecord(page=page, pdf_path=destination))

        if manifest_records:
            summary.manifest_path = output_space_dir / MANIFEST_FILENAME
            update_manifest(summary.manifest_path, manifest_records)

        return summary

    def _collect_pages(self, space_key: str, titles: list[str], include_children: bool) -> list[Page]:
        pages: list[Page] = []
        seen_ids: set[str] = set()

        for title in titles:
            root = self.client.resolve_page_by_title(space_key, title)
            page_group = [root]
            if include_children:
                page_group.extend(self.client.iter_descendants(root))

            for page in page_group:
                if page.id not in seen_ids:
                    pages.append(page)
                    seen_ids.add(page.id)

        return pages


def build_pdf_filename(index: int, page: Page) -> str:
    return f"{index:04d}-{page.id}-{slugify_title(page.title)}.pdf"
