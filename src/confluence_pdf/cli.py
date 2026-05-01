from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from .client import ConfluenceClient
from .config import BulkPageRequest, read_bulk_config, update_bulk_config
from .downloader import PdfDownloader
from .errors import ConfigError, ConfluencePdfError
from .tree import TreePage, list_space_tree
from .utils import merge_titles, normalize_base_url

app = typer.Typer(help="Download Confluence Data Center pages as PDFs.")


@app.callback()
def main() -> None:
    """Download Confluence Data Center pages as PDFs."""


@app.command()
def download(
    space: Annotated[str, typer.Option("--space", help="Confluence space key.")],
    title: Annotated[
        list[str] | None,
        typer.Option("--title", help="Confluence page title. Repeat for multiple pages."),
    ] = None,
    titles_file: Annotated[
        Path | None,
        typer.Option("--titles-file", exists=True, dir_okay=False, help="Newline-delimited page titles."),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", file_okay=False, help="Directory where PDFs are written."),
    ] = Path("pdfs"),
    include_children: Annotated[
        bool,
        typer.Option("--include-children", help="Download each page plus all descendants."),
    ] = False,
    combine_children: Annotated[
        bool,
        typer.Option(
            "--combine-children/--separate-pages",
            help="When including children, write one combined PDF per root instead of one PDF per page.",
        ),
    ] = True,
    force: Annotated[
        bool,
        typer.Option("--force", help="Regenerate PDFs even when a valid PDF already exists."),
    ] = False,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", envvar="CONFLUENCE_BASE_URL", help="Confluence base URL."),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option("--token", envvar="CONFLUENCE_PAT", help="Confluence Personal Access Token."),
    ] = None,
    request_delay: Annotated[
        float,
        typer.Option("--request-delay", min=0.0, help="Minimum delay in seconds between Confluence requests."),
    ] = 0.0,
    retry_backoff: Annotated[
        float,
        typer.Option("--retry-backoff", min=0.0, help="Initial 429 retry backoff in seconds."),
    ] = 1.0,
    max_retries: Annotated[
        int,
        typer.Option("--max-retries", min=0, help="Maximum number of retries for HTTP 429 responses."),
    ] = 3,
    verbosity: Annotated[
        str,
        typer.Option("--verbosity", help="Progress log verbosity: quiet, normal, or verbose."),
    ] = "quiet",
) -> None:
    """Download selected Confluence pages as individual PDF files."""
    try:
        resolved_base_url = _required_base_url(base_url)
        resolved_token = _required_token(token)
        titles = merge_titles(title, titles_file)
        if not titles:
            raise ConfigError("Provide at least one --title or --titles-file entry.")

        logger = _make_logger(verbosity)
        with ConfluenceClient(
            resolved_base_url,
            resolved_token,
            request_delay=request_delay,
            retry_backoff=retry_backoff,
            max_retries=max_retries,
        ) as client:
            downloader = PdfDownloader(client, logger=logger)
            summary = downloader.download(
                space_key=space,
                titles=titles,
                output_dir=output_dir,
                include_children=include_children,
                force=force,
                combine_children=combine_children,
            )

        _print_summary(summary, output_dir / space)
        if summary.failed:
            raise typer.Exit(code=1)
    except ConfluencePdfError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def bulk(
    config: Annotated[
        Path,
        typer.Option("--config", exists=True, dir_okay=False, help="JSON bulk download configuration."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", file_okay=False, help="Directory where PDFs are written."),
    ] = Path("pdfs"),
    force: Annotated[
        bool,
        typer.Option("--force", help="Regenerate PDFs even when the manifest version is unchanged."),
    ] = False,
    group_by_page: Annotated[
        bool,
        typer.Option(
            "--group-by-page/--group-by-space",
            help="Run each configured page as its own group, or combine pages by space and include_children.",
        ),
    ] = True,
    combine_children: Annotated[
        bool,
        typer.Option(
            "--combine-children/--separate-pages",
            help="When include_children is true, write one combined PDF per configured root.",
        ),
    ] = True,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", envvar="CONFLUENCE_BASE_URL", help="Confluence base URL."),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option("--token", envvar="CONFLUENCE_PAT", help="Confluence Personal Access Token."),
    ] = None,
    request_delay: Annotated[
        float,
        typer.Option("--request-delay", min=0.0, help="Minimum delay in seconds between Confluence requests."),
    ] = 0.0,
    retry_backoff: Annotated[
        float,
        typer.Option("--retry-backoff", min=0.0, help="Initial 429 retry backoff in seconds."),
    ] = 1.0,
    max_retries: Annotated[
        int,
        typer.Option("--max-retries", min=0, help="Maximum number of retries for HTTP 429 responses."),
    ] = 3,
    verbosity: Annotated[
        str,
        typer.Option("--verbosity", help="Progress log verbosity: quiet, normal, or verbose."),
    ] = "normal",
) -> None:
    """Download pages from a JSON config, skipping unchanged versions."""
    try:
        resolved_base_url = _required_base_url(base_url)
        resolved_token = _required_token(token)
        requests = read_bulk_config(config)

        groups = _group_bulk_requests(requests, group_by_page=group_by_page)
        logger = _make_logger(verbosity)
        _log(logger, "normal", f"Bulk config pages: {len(requests)}")
        _log(logger, "normal", f"Download groups: {len(groups)}")
        _log(logger, "normal", f"Grouping: {'page' if group_by_page else 'space'}")
        if not force:
            _log(logger, "normal", "Version cache: skipping unchanged pages from downloaded_pages.md")

        failed = False
        with ConfluenceClient(
            resolved_base_url,
            resolved_token,
            request_delay=request_delay,
            retry_backoff=retry_backoff,
            max_retries=max_retries,
        ) as client:
            downloader = PdfDownloader(client, logger=logger)
            for group_index, group in enumerate(groups, start=1):
                _log(
                    logger,
                    "normal",
                    f"Group {group_index}/{len(groups)}: space={group.space} "
                    f"include_children={group.include_children} roots={len(group.titles)}",
                )
                _log(logger, "normal", "roots:")
                for title in group.titles:
                    _log(logger, "normal", f"- {title}")
                _log(logger, "normal", "starting page discovery/download")
                summary = downloader.download(
                    space_key=group.space,
                    titles=group.titles,
                    output_dir=output_dir,
                    include_children=group.include_children,
                    force=force,
                    skip_unchanged=True,
                    combine_children=combine_children,
                )
                _print_summary(summary, output_dir / group.space)
                if summary.failed:
                    failed = True

        if failed:
            raise typer.Exit(code=1)
    except ConfluencePdfError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("list-space")
def list_space(
    space: Annotated[str, typer.Option("--space", help="Confluence space key.")],
    depth: Annotated[
        int,
        typer.Option("--depth", min=1, help="Tree depth to list. Root pages are depth 1."),
    ],
    root_title: Annotated[
        str | None,
        typer.Option(
            "--root-title",
            help="Start listing at this page title instead of listing every root page in the space.",
        ),
    ] = None,
    bulk_config: Annotated[
        Path | None,
        typer.Option(
            "--bulk-config",
            dir_okay=False,
            help="Create or update a JSON bulk config with pages at the final listed depth.",
        ),
    ] = None,
    bulk_include_children: Annotated[
        bool,
        typer.Option(
            "--bulk-include-children/--no-bulk-include-children",
            help="Set include_children for generated final-depth bulk config entries.",
        ),
    ] = True,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", envvar="CONFLUENCE_BASE_URL", help="Confluence base URL."),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option("--token", envvar="CONFLUENCE_PAT", help="Confluence Personal Access Token."),
    ] = None,
    request_delay: Annotated[
        float,
        typer.Option("--request-delay", min=0.0, help="Minimum delay in seconds between Confluence requests."),
    ] = 0.0,
    retry_backoff: Annotated[
        float,
        typer.Option("--retry-backoff", min=0.0, help="Initial 429 retry backoff in seconds."),
    ] = 1.0,
    max_retries: Annotated[
        int,
        typer.Option("--max-retries", min=0, help="Maximum number of retries for HTTP 429 responses."),
    ] = 3,
) -> None:
    """List a space page tree and optionally update a bulk config from the final depth."""
    try:
        resolved_base_url = _required_base_url(base_url)
        resolved_token = _required_token(token)

        with ConfluenceClient(
            resolved_base_url,
            resolved_token,
            request_delay=request_delay,
            retry_backoff=retry_backoff,
            max_retries=max_retries,
        ) as client:
            tree_pages = list_space_tree(
                client,
                space_key=space,
                max_depth=depth,
                root_title=root_title,
            )

        for tree_page in tree_pages:
            typer.echo(_format_tree_page(tree_page))

        final_depth_pages = [tree_page for tree_page in tree_pages if tree_page.depth == depth]
        if bulk_config:
            update_bulk_config(
                bulk_config,
                [
                    BulkPageRequest(
                        space=space,
                        title=tree_page.page.title,
                        include_children=bulk_include_children,
                    )
                    for tree_page in final_depth_pages
                ],
            )
            typer.echo(f"Bulk config updated: {bulk_config}")
            typer.echo(f"Final-depth pages written: {len(final_depth_pages)}")
    except ConfluencePdfError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _required_base_url(base_url: str | None) -> str:
    value = base_url or os.environ.get("CONFLUENCE_BASE_URL")
    if not value:
        raise ConfigError("Provide --base-url or set CONFLUENCE_BASE_URL.")
    return normalize_base_url(value)


def _required_token(token: str | None) -> str:
    value = token or os.environ.get("CONFLUENCE_PAT")
    if not value:
        raise ConfigError("Provide --token or set CONFLUENCE_PAT.")
    return value


def _print_summary(summary, output_path: Path) -> None:
    rows = [
        ("Roots requested", str(summary.roots_requested)),
        ("Pages found", str(summary.pages_found)),
        ("Exported", str(len(summary.exported))),
        ("Skipped existing", str(len(summary.skipped))),
        ("Skipped unchanged", str(len(summary.skipped_unchanged))),
        ("Failed", str(summary.failed)),
        ("Output directory", str(output_path)),
    ]
    if summary.manifest_path:
        rows.append(("Manifest", str(summary.manifest_path)))
    _print_box("📊 Group Summary", rows)
    for failure in summary.failures:
        typer.echo(f"- {failure.page.id} {failure.page.title}: {failure.error}", err=True)


def _print_box(title: str, rows: list[tuple[str, str]]) -> None:
    rendered_rows = [f"{label}: {value}" for label, value in rows]
    width = max(len(title), *(len(row) for row in rendered_rows))
    typer.echo(f"┌─ {title}{'─' * (width - len(title) + 1)}┐")
    for row in rendered_rows:
        typer.echo(f"│ {row}{' ' * (width - len(row))} │")
    typer.echo(f"└{'─' * (width + 2)}┘")


def _make_logger(verbosity: str) -> LogFn | None:
    allowed = {"quiet", "normal", "verbose"}
    if verbosity not in allowed:
        raise ConfigError("--verbosity must be one of: quiet, normal, verbose.")
    if verbosity == "quiet":
        return None
    max_level = {"normal": 1, "verbose": 2}[verbosity]

    def logger(level: str, message: str) -> None:
        if {"normal": 1, "verbose": 2}.get(level, 1) <= max_level:
            typer.echo(_decorate_log(message))

    return logger


LogFn = Callable[[str, str], None]


def _log(logger: LogFn | None, level: str, message: str) -> None:
    if logger:
        logger(level, message)


def _decorate_log(message: str) -> str:
    stripped = message.strip()
    lower = stripped.lower()
    if lower.startswith("group "):
        icon = "📦"
    elif lower.startswith("bulk config") or lower.startswith("download groups") or lower.startswith("grouping"):
        icon = "📋"
    elif lower.startswith("version cache"):
        icon = "🧠"
    elif lower == "roots:" or lower.startswith("- "):
        icon = "🌱"
    elif lower.startswith("resolving root") or lower.startswith("resolved:"):
        icon = "🔎"
    elif lower.startswith("listing descendants") or lower.startswith("found ") or lower.startswith("checking children") or lower.startswith("checked "):
        icon = "🌳"
    elif lower.startswith("["):
        icon = "📄"
    elif lower.startswith("unchanged") or lower.startswith("existing valid"):
        icon = "⏭️"
    elif lower.startswith("downloading"):
        icon = "⬇️"
    elif lower == "done":
        icon = "✅"
    elif lower.startswith("failed"):
        icon = "❌"
    elif lower.startswith("starting"):
        icon = "🚀"
    else:
        icon = "ℹ️"
    return f"{icon} {message}"


class _BulkGroup:
    def __init__(self, space: str, include_children: bool) -> None:
        self.space = space
        self.include_children = include_children
        self.titles: list[str] = []


def _group_bulk_requests(requests: list[BulkPageRequest], *, group_by_page: bool) -> list[_BulkGroup]:
    if group_by_page:
        groups: list[_BulkGroup] = []
        for request in requests:
            group = _BulkGroup(space=request.space, include_children=request.include_children)
            group.titles.append(request.title)
            groups.append(group)
        return groups

    groups_by_key: dict[tuple[str, bool], _BulkGroup] = {}
    for request in requests:
        key = (request.space, request.include_children)
        if key not in groups_by_key:
            groups_by_key[key] = _BulkGroup(
                space=request.space,
                include_children=request.include_children,
            )
        if request.title not in groups_by_key[key].titles:
            groups_by_key[key].titles.append(request.title)
    return list(groups_by_key.values())


def _format_tree_page(tree_page: TreePage) -> str:
    indent = "  " * (tree_page.depth - 1)
    version = "" if tree_page.page.version is None else f" v{tree_page.page.version}"
    return f"{indent}- {tree_page.page.title} [{tree_page.page.id}]{version}"


if __name__ == "__main__":
    app()
