from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..config import BulkPageRequest
from ..downloader import DownloadSummary, LogFn
from ..errors import ConfluencePdfError
from ..models import Page
from ..utils import bulk_requests_from_pages, titles_by_space


@dataclass
class DownloadPlan:
    pages: list[Page]
    include_children: bool = False
    combine_children: bool = False
    download_html: bool = False
    force: bool = False
    fallback_space: str | None = None

    def bulk_requests(self) -> list[BulkPageRequest]:
        return bulk_requests_from_pages(
            self.pages,
            include_children=self.include_children,
            fallback_space=self.fallback_space,
        )


@dataclass
class PlanResult:
    summaries: list[DownloadSummary] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def exported(self) -> int:
        return sum(len(summary.exported) for summary in self.summaries)

    @property
    def skipped(self) -> int:
        return sum(len(summary.skipped) for summary in self.summaries)

    @property
    def skipped_unchanged(self) -> int:
        return sum(len(summary.skipped_unchanged) for summary in self.summaries)

    @property
    def failed(self) -> int:
        return sum(summary.failed for summary in self.summaries)

    @property
    def cancelled(self) -> bool:
        return any(summary.cancelled for summary in self.summaries)

    @property
    def manifest_path(self) -> Path | None:
        for summary in reversed(self.summaries):
            if summary.manifest_path:
                return summary.manifest_path
        return None


def execute_plan(
    plan: DownloadPlan,
    downloader,
    *,
    output_dir: Path,
    should_stop: Callable[[], bool] | None = None,
    log: LogFn | None = None,
) -> PlanResult:
    result = PlanResult()
    for space, titles in titles_by_space(plan.pages, fallback_space=plan.fallback_space).items():
        if should_stop and should_stop():
            break
        try:
            summary = downloader.download(
                space_key=space,
                titles=titles,
                output_dir=output_dir,
                include_children=plan.include_children,
                force=plan.force,
                skip_unchanged=True,
                combine_children=plan.combine_children,
                download_html=plan.download_html,
            )
        except ConfluencePdfError as exc:
            result.errors.append(str(exc))
            if log:
                log("normal", f"failed: {exc}")
            continue
        result.summaries.append(summary)
        if summary.cancelled:
            break
    return result
