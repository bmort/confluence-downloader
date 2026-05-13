from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .client import ConfluenceClient
from .errors import PdfExportError
from .manifest import (
    HTML_MANIFEST_FILENAME,
    MANIFEST_FILENAME,
    ManifestRecord,
    read_manifest_entries,
    update_manifest,
)
from .models import Page
from .render import is_pdf_file
from .utils import slugify_title

HTML_OUTPUT_DIRNAME = "html"


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
    skipped_unchanged: list[Path] = field(default_factory=list)
    failures: list[DownloadFailure] = field(default_factory=list)
    manifest_path: Path | None = None
    html_manifest_path: Path | None = None

    @property
    def failed(self) -> int:
        return len(self.failures)


LogFn = Callable[[str, str], None]


class PdfDownloader:
    def __init__(self, client: ConfluenceClient, *, logger: LogFn | None = None) -> None:
        self.client = client
        self.logger = logger

    def download(
        self,
        *,
        space_key: str,
        titles: list[str],
        output_dir: Path,
        include_children: bool,
        force: bool = False,
        skip_unchanged: bool = False,
        combine_children: bool = False,
        download_html: bool = False,
    ) -> DownloadSummary:
        summary = DownloadSummary(roots_requested=len(titles))
        output_dir.mkdir(parents=True, exist_ok=True)

        if combine_children and include_children:
            return self._download_combined_roots(
                space_key=space_key,
                titles=titles,
                output_dir=output_dir,
                force=force,
                skip_unchanged=skip_unchanged,
                download_html=download_html,
            )

        pages = self._collect_pages(space_key, titles, include_children)
        summary.pages_found = len(pages)
        manifest_records: list[ManifestRecord] = []
        manifest_path = output_dir / MANIFEST_FILENAME
        manifest_entries = read_manifest_entries(manifest_path) if skip_unchanged else {}

        for index, page in enumerate(pages, start=1):
            destination = output_dir / build_pdf_filename(page)
            html_destination = build_html_destination(output_dir, page)
            self._log(
                f"[{index}/{len(pages)}] {page.title} "
                f"(id={page.id}, version={page.version if page.version is not None else 'unknown'})"
            )
            unchanged_destination = find_unchanged_pdf(output_dir, page, manifest_entries)
            if not force and skip_unchanged and unchanged_destination:
                self._log(f"unchanged; skipping {unchanged_destination.name}")
                html_path = self._optional_html_copy(
                    page,
                    html_destination,
                    force=force,
                    summary=summary,
                    download_html=download_html,
                )
                summary.skipped_unchanged.append(unchanged_destination)
                manifest_records.append(
                    ManifestRecord(page=page, pdf_path=unchanged_destination, html_path=html_path)
                )
                continue
            if not force and destination.exists() and is_pdf_file(destination):
                self._log(f"existing valid PDF; skipping {destination.name}")
                html_path = self._optional_html_copy(
                    page,
                    html_destination,
                    force=force,
                    summary=summary,
                    download_html=download_html,
                )
                summary.skipped.append(destination)
                manifest_records.append(
                    ManifestRecord(page=page, pdf_path=destination, html_path=html_path)
                )
                continue
            try:
                self._log(f"downloading -> {destination.name}")
                self.client.download_pdf(page, destination)
            except PdfExportError as exc:
                self._log(f"failed: {exc}")
                summary.failures.append(DownloadFailure(page=page, error=str(exc)))
                continue
            html_path = self._optional_html_copy(
                page,
                html_destination,
                force=force,
                summary=summary,
                download_html=download_html,
            )
            self._log("done")
            summary.exported.append(destination)
            manifest_records.append(ManifestRecord(page=page, pdf_path=destination, html_path=html_path))

        if manifest_records:
            summary.manifest_path = manifest_path
            summary.html_manifest_path = manifest_path.with_name(HTML_MANIFEST_FILENAME)
            update_manifest(summary.manifest_path, manifest_records)

        return summary

    def _download_combined_roots(
        self,
        *,
        space_key: str,
        titles: list[str],
        output_dir: Path,
        force: bool,
        skip_unchanged: bool,
        download_html: bool,
    ) -> DownloadSummary:
        summary = DownloadSummary(roots_requested=len(titles))
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / MANIFEST_FILENAME
        manifest_entries = read_manifest_entries(manifest_path) if skip_unchanged else {}
        manifest_records: list[ManifestRecord] = []
        seen_ids: set[str] = set()

        for root_index, title in enumerate(titles, start=1):
            self._log(f"Resolving root {root_index}/{len(titles)}: {title}")
            root = self.client.resolve_page_by_title(space_key, title)
            self._log(f"resolved: {root.title} (id={root.id}, version={root.version if root.version is not None else 'unknown'})")
            self._log(f"listing descendants for {root.title}")
            page_group = [root, *self._iter_descendants_with_progress(root)]
            self._log(f"found {len(page_group) - 1} descendants")
            unique_page_group = [page for page in page_group if page.id not in seen_ids]
            seen_ids.update(page.id for page in unique_page_group)
            summary.pages_found += len(unique_page_group)
            destination = output_dir / build_combined_pdf_filename(root)
            html_destinations = {
                page.id: build_html_destination(output_dir, page) for page in unique_page_group
            }

            if not force and all_pages_unchanged(output_dir, unique_page_group, manifest_entries):
                self._log(f"combined subtree unchanged; skipping {destination.name}")
                html_paths = {
                    page.id: self._optional_html_copy(
                        page,
                        html_destinations[page.id],
                        force=force,
                        summary=summary,
                        download_html=download_html,
                    )
                    for page in unique_page_group
                }
                summary.skipped_unchanged.append(destination)
                manifest_records.extend(
                    ManifestRecord(page=page, pdf_path=destination, html_path=html_paths[page.id])
                    for page in unique_page_group
                )
                continue
            if not force and destination.exists() and is_pdf_file(destination):
                self._log(f"existing valid combined PDF; skipping {destination.name}")
                html_paths = {
                    page.id: self._optional_html_copy(
                        page,
                        html_destinations[page.id],
                        force=force,
                        summary=summary,
                        download_html=download_html,
                    )
                    for page in unique_page_group
                }
                summary.skipped.append(destination)
                manifest_records.extend(
                    ManifestRecord(page=page, pdf_path=destination, html_path=html_paths[page.id])
                    for page in unique_page_group
                )
                continue

            try:
                self._log(f"downloading combined PDF -> {destination.name}")
                self.client.download_combined_pdf(unique_page_group, destination)
            except PdfExportError as exc:
                self._log(f"failed: {exc}")
                summary.failures.append(DownloadFailure(page=root, error=str(exc)))
                continue
            html_paths = {
                page.id: self._optional_html_copy(
                    page,
                    html_destinations[page.id],
                    force=force,
                    summary=summary,
                    download_html=download_html,
                )
                for page in unique_page_group
            }
            self._log("done")
            summary.exported.append(destination)
            manifest_records.extend(
                ManifestRecord(page=page, pdf_path=destination, html_path=html_paths[page.id])
                for page in unique_page_group
            )

        if manifest_records:
            summary.manifest_path = manifest_path
            summary.html_manifest_path = manifest_path.with_name(HTML_MANIFEST_FILENAME)
            update_manifest(summary.manifest_path, manifest_records)

        return summary

    def _collect_pages(self, space_key: str, titles: list[str], include_children: bool) -> list[Page]:
        pages: list[Page] = []
        seen_ids: set[str] = set()

        for title_index, title in enumerate(titles, start=1):
            self._log(f"Resolving root {title_index}/{len(titles)}: {title}")
            root = self.client.resolve_page_by_title(space_key, title)
            self._log(f"resolved: {root.title} (id={root.id}, version={root.version if root.version is not None else 'unknown'})")
            page_group = [root]
            if include_children:
                self._log(f"listing descendants for {root.title}")
                page_group.extend(self._iter_descendants_with_progress(root))
                self._log(f"found {len(page_group) - 1} descendants")

            for page in page_group:
                if page.id not in seen_ids:
                    pages.append(page)
                    seen_ids.add(page.id)

        return pages

    def _iter_descendants_with_progress(self, root: Page) -> list[Page]:
        descendants: list[Page] = []
        stack = [root]
        visited_parents = 0

        while stack:
            parent = stack.pop()
            visited_parents += 1
            self._log(f"checking children of {parent.title} (id={parent.id})", level="verbose")
            children = self.client.list_child_pages(parent.id)
            self._log(
                f"    found {len(children)} children under {parent.title}; "
                f"descendants discovered so far: {len(descendants) + len(children)}",
                level="verbose",
            )
            descendants.extend(children)
            stack.extend(reversed(children))

        self._log(f"checked {visited_parents} pages while walking descendants", level="verbose")
        return descendants

    def _log(self, message: str, *, level: str = "normal") -> None:
        if self.logger:
            self.logger(level, message)

    def _ensure_html_copy(
        self,
        page: Page,
        destination: Path,
        *,
        force: bool,
        summary: DownloadSummary,
    ) -> Path | None:
        if not force and destination.exists():
            self._log(f"existing HTML; skipping {destination.name}", level="verbose")
            return destination
        try:
            self._log(f"writing HTML -> {destination.name}", level="verbose")
            destination.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_html(page, destination)
        except PdfExportError as exc:
            self._log(f"HTML failed: {exc}")
            summary.failures.append(DownloadFailure(page=page, error=str(exc)))
            return None
        return destination

    def _optional_html_copy(
        self,
        page: Page,
        destination: Path,
        *,
        force: bool,
        summary: DownloadSummary,
        download_html: bool,
    ) -> Path | None:
        if not download_html:
            return None
        return self._ensure_html_copy(
            page,
            destination,
            force=force,
            summary=summary,
        )


def build_pdf_filename(page: Page) -> str:
    version = "" if page.version is None else f"-v{page.version}"
    return f"{slugify_title(page.title)}-{page.id}{version}.pdf"


def build_html_filename(page: Page) -> str:
    version = "" if page.version is None else f"-v{page.version}"
    return f"{slugify_title(page.title)}-{page.id}{version}.html"


def build_html_destination(output_dir: Path, page: Page) -> Path:
    return output_dir / HTML_OUTPUT_DIRNAME / build_html_filename(page)


def build_combined_pdf_filename(page: Page) -> str:
    return f"{slugify_title(page.title)}-combined-{page.id}.pdf"


def find_unchanged_pdf(output_dir: Path, page: Page, manifest_entries: dict) -> Path | None:
    if page.version is None:
        return None
    entry = manifest_entries.get(page.id)
    if entry and entry.version == page.version:
        candidate = output_dir / entry.pdf_name
        if candidate.exists() and is_pdf_file(candidate):
            return candidate
    filename_candidate = output_dir / build_pdf_filename(page)
    if filename_candidate.exists() and is_pdf_file(filename_candidate):
        return filename_candidate
    for candidate in output_dir.glob(f"*-{page.id}-v*.pdf"):
        if _filename_version(candidate, page.id) == page.version and is_pdf_file(candidate):
            return candidate
    return None


def all_pages_unchanged(output_dir: Path, pages: list[Page], manifest_entries: dict) -> bool:
    if not pages:
        return False
    destinations: set[Path] = set()
    for page in pages:
        unchanged = find_unchanged_pdf(output_dir, page, manifest_entries)
        if not unchanged:
            return False
        destinations.add(unchanged)
    return len(destinations) == 1


def _filename_version(path: Path, page_id: str) -> int | None:
    match = re.search(rf"-{re.escape(page_id)}-v([0-9]+)\.pdf$", path.name)
    if not match:
        return None
    return int(match.group(1))
