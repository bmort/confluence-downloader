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

app = typer.Typer(
    help="Download Confluence Data Center pages as PDFs.",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.callback()
def main(ctx: typer.Context) -> None:
    """Download Confluence Data Center pages as PDFs."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command()
def download(
    ctx: typer.Context,
    space: Annotated[str | None, typer.Option("--space", "-s", help="Required: Confluence space key.")] = None,
    title: Annotated[
        list[str] | None,
        typer.Option(
            "--title",
            "-t",
            help="Required unless --titles-file is used: Confluence page title. Repeat for multiple pages.",
        ),
    ] = None,
    titles_file: Annotated[
        Path | None,
        typer.Option(
            "--titles-file",
            "-T",
            exists=True,
            dir_okay=False,
            help="Required unless --title is used: Newline-delimited page titles.",
        ),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", "-o", file_okay=False, help="Optional: Directory where PDFs are written."),
    ] = Path("."),
    include_children: Annotated[
        bool,
        typer.Option("--include-children", "-i", help="Optional: Download each page plus all descendants."),
    ] = False,
    combine_children: Annotated[
        bool,
        typer.Option(
            "--combine-children/--separate-pages",
            "-c/-p",
            help="Optional: When including children, write one combined PDF per root instead of one PDF per page.",
        ),
    ] = True,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Optional: Regenerate PDFs even when a valid PDF already exists."),
    ] = False,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            "-b",
            envvar="CONFLUENCE_BASE_URL",
            help="Required unless CONFLUENCE_BASE_URL is set: Confluence base URL.",
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-k",
            envvar="CONFLUENCE_PAT",
            help="Required unless CONFLUENCE_PAT is set: Confluence Personal Access Token.",
        ),
    ] = None,
    request_delay: Annotated[
        float,
        typer.Option(
            "--request-delay",
            "-d",
            min=0.0,
            help="Optional: Minimum delay in seconds between Confluence requests.",
        ),
    ] = 0.0,
    retry_backoff: Annotated[
        float,
        typer.Option("--retry-backoff", "-r", min=0.0, help="Optional: Initial 429 retry backoff in seconds."),
    ] = 1.0,
    max_retries: Annotated[
        int,
        typer.Option("--max-retries", "-m", min=0, help="Optional: Maximum number of retries for HTTP 429 responses."),
    ] = 3,
    verbosity: Annotated[
        str,
        typer.Option("--verbosity", "-v", help="Optional: Progress log verbosity: quiet, normal, or verbose."),
    ] = "normal",
) -> None:
    """Download selected Confluence pages as individual PDF files."""
    if not ctx.args and ctx.params.get("space") is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()

    try:
        resolved_base_url = _required_base_url(base_url)
        resolved_token = _required_token(token)
        if space is None:
            raise ConfigError("Provide --space.")
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

        _print_summary(summary, output_dir)
        if summary.failed:
            raise typer.Exit(code=1)
    except ConfluencePdfError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def bulk(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", exists=True, dir_okay=False, help="Required: JSON bulk download configuration."),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", "-o", file_okay=False, help="Optional: Directory where PDFs are written."),
    ] = Path("."),
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Optional: Regenerate PDFs even when the manifest version is unchanged."),
    ] = False,
    group_by_page: Annotated[
        bool,
        typer.Option(
            "--group-by-page/--group-by-space",
            "-g/-G",
            help="Optional: Run each configured page as its own group, or combine pages by space and include_children.",
        ),
    ] = True,
    combine_children: Annotated[
        bool,
        typer.Option(
            "--combine-children/--separate-pages",
            "-C/-p",
            help="Optional: When include_children is true, write one combined PDF per configured root.",
        ),
    ] = True,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            "-b",
            envvar="CONFLUENCE_BASE_URL",
            help="Required unless CONFLUENCE_BASE_URL is set: Confluence base URL.",
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-k",
            envvar="CONFLUENCE_PAT",
            help="Required unless CONFLUENCE_PAT is set: Confluence Personal Access Token.",
        ),
    ] = None,
    request_delay: Annotated[
        float,
        typer.Option(
            "--request-delay",
            "-d",
            min=0.0,
            help="Optional: Minimum delay in seconds between Confluence requests.",
        ),
    ] = 0.0,
    retry_backoff: Annotated[
        float,
        typer.Option("--retry-backoff", "-r", min=0.0, help="Optional: Initial 429 retry backoff in seconds."),
    ] = 1.0,
    max_retries: Annotated[
        int,
        typer.Option("--max-retries", "-m", min=0, help="Optional: Maximum number of retries for HTTP 429 responses."),
    ] = 3,
    verbosity: Annotated[
        str,
        typer.Option("--verbosity", "-v", help="Optional: Progress log verbosity: quiet, normal, or verbose."),
    ] = "normal",
) -> None:
    """Download pages from a JSON config, skipping unchanged versions."""
    if not ctx.args and config is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()

    try:
        resolved_base_url = _required_base_url(base_url)
        resolved_token = _required_token(token)
        if config is None:
            raise ConfigError("Provide --config.")
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
                _print_summary(summary, output_dir)
                if summary.failed:
                    failed = True

        if failed:
            raise typer.Exit(code=1)
    except ConfluencePdfError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("list-space")
def list_space(
    ctx: typer.Context,
    space: Annotated[str | None, typer.Option("--space", "-s", help="Required: Confluence space key.")] = None,
    depth: Annotated[
        int | None,
        typer.Option("--depth", "-d", min=1, help="Required: Tree depth to list. Root pages are depth 1."),
    ] = None,
    root_title: Annotated[
        str | None,
        typer.Option(
            "--root-title",
            "-r",
            help="Optional: Start listing at this page title instead of listing every root page in the space.",
        ),
    ] = None,
    bulk_config: Annotated[
        Path | None,
        typer.Option(
            "--bulk-config",
            "-c",
            dir_okay=False,
            help="Optional: Create or update a JSON bulk config with pages at the final listed depth.",
        ),
    ] = None,
    bulk_include_children: Annotated[
        bool,
        typer.Option(
            "--bulk-include-children/--no-bulk-include-children",
            "-i/-I",
            help="Optional: Set include_children for generated final-depth bulk config entries.",
        ),
    ] = True,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            "-b",
            envvar="CONFLUENCE_BASE_URL",
            help="Required unless CONFLUENCE_BASE_URL is set: Confluence base URL.",
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-k",
            envvar="CONFLUENCE_PAT",
            help="Required unless CONFLUENCE_PAT is set: Confluence Personal Access Token.",
        ),
    ] = None,
    request_delay: Annotated[
        float,
        typer.Option(
            "--request-delay",
            "-D",
            min=0.0,
            help="Optional: Minimum delay in seconds between Confluence requests.",
        ),
    ] = 0.0,
    retry_backoff: Annotated[
        float,
        typer.Option("--retry-backoff", "-R", min=0.0, help="Optional: Initial 429 retry backoff in seconds."),
    ] = 1.0,
    max_retries: Annotated[
        int,
        typer.Option("--max-retries", "-m", min=0, help="Optional: Maximum number of retries for HTTP 429 responses."),
    ] = 3,
) -> None:
    """List a space page tree and optionally update a bulk config from the final depth."""
    if not ctx.args and ctx.params.get("space") is None and depth is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()

    try:
        resolved_base_url = _required_base_url(base_url)
        resolved_token = _required_token(token)
        if space is None:
            raise ConfigError("Provide --space.")
        if depth is None:
            raise ConfigError("Provide --depth.")

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


@app.command()
def search(
    ctx: typer.Context,
    query: Annotated[
        str | None,
        typer.Argument(help="Required: Search string to match against Confluence page titles."),
    ] = None,
    space: Annotated[
        str | None,
        typer.Option("--space", "-s", help="Optional: Restrict search to this Confluence space key."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", min=1, max=100, help="Optional: Maximum number of matches to return."),
    ] = 10,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            "-b",
            envvar="CONFLUENCE_BASE_URL",
            help="Required unless CONFLUENCE_BASE_URL is set: Confluence base URL.",
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-k",
            envvar="CONFLUENCE_PAT",
            help="Required unless CONFLUENCE_PAT is set: Confluence Personal Access Token.",
        ),
    ] = None,
    request_delay: Annotated[
        float,
        typer.Option(
            "--request-delay",
            "-d",
            min=0.0,
            help="Optional: Minimum delay in seconds between Confluence requests.",
        ),
    ] = 0.0,
    retry_backoff: Annotated[
        float,
        typer.Option("--retry-backoff", "-r", min=0.0, help="Optional: Initial 429 retry backoff in seconds."),
    ] = 1.0,
    max_retries: Annotated[
        int,
        typer.Option("--max-retries", "-m", min=0, help="Optional: Maximum number of retries for HTTP 429 responses."),
    ] = 3,
) -> None:
    """Search Confluence page titles for close matches."""
    if query is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()

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
            pages = client.search_pages_by_title(query, space_key=space, limit=limit)

        if not pages:
            scope = f" in space {space}" if space else ""
            typer.echo(f'No matching pages found for "{query}"{scope}.')
            return

        rows = [
            ("Page ID", "Space", "Title", "URL"),
            *[(page.id, page.space, page.title, page.url) for page in pages],
        ]
        _print_table(rows)
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


def _print_table(rows: list[tuple[str, ...]]) -> None:
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    for row_index, row in enumerate(rows):
        typer.echo("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
        if row_index == 0:
            typer.echo("  ".join("-" * width for width in widths))


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
    metadata = f"id={tree_page.page.id}"
    if tree_page.page.version is not None:
        metadata = f"{metadata} version={tree_page.page.version}"
    return f'{indent}- "{tree_page.page.title}" | {metadata}'


if __name__ == "__main__":
    app()
