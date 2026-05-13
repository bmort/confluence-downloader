from __future__ import annotations

from datetime import datetime, timezone
import os
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer
from click.core import ParameterSource

from .client import ConfluenceClient
from .config import BulkPageRequest, read_bulk_config_details, update_bulk_config
from .downloader import PdfDownloader
from .errors import ConfigError, ConfluencePdfError
from .models import Page
from .tree import TreePage, list_space_tree
from .utils import merge_titles, normalize_base_url

app = typer.Typer(
    help="Download Confluence Data Center pages as PDFs.",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

REQUIRED_HELP_PANEL = "Required options"
OPTIONAL_HELP_PANEL = "Optional options"
CONNECTION_HELP_PANEL = "Confluence connection"


@app.callback()
def main(ctx: typer.Context) -> None:
    """Download Confluence Data Center pages as PDFs."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command()
def download(
    ctx: typer.Context,
    space: Annotated[
        str | None,
        typer.Option("--space", "-s", help="Confluence space key.", rich_help_panel=REQUIRED_HELP_PANEL),
    ] = None,
    title: Annotated[
        list[str] | None,
        typer.Option(
            "--title",
            "-t",
            help="Confluence page title. Repeat for multiple pages. Required unless --titles-file is used.",
            rich_help_panel=REQUIRED_HELP_PANEL,
        ),
    ] = None,
    titles_file: Annotated[
        Path | None,
        typer.Option(
            "--titles-file",
            "-T",
            exists=True,
            dir_okay=False,
            help="Newline-delimited page titles. Required unless --title is used.",
            rich_help_panel=REQUIRED_HELP_PANEL,
        ),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            file_okay=False,
            help="Directory where PDFs are written.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = Path("."),
    include_children: Annotated[
        bool,
        typer.Option(
            "--include-children",
            "-i",
            help="Download each page plus all descendants.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    combine_children: Annotated[
        bool,
        typer.Option(
            "--combine-children/--separate-pages",
            "-c/-p",
            help="When including children, write one combined PDF per root instead of one PDF per page.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = True,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Regenerate PDFs even when a valid PDF already exists.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    download_html: Annotated[
        bool,
        typer.Option(
            "--download-html",
            help="Also download each Confluence page as a standalone HTML file.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            "-b",
            envvar="CONFLUENCE_BASE_URL",
            help="Confluence base URL. Required unless CONFLUENCE_BASE_URL is set.",
            rich_help_panel=CONNECTION_HELP_PANEL,
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-k",
            envvar="CONFLUENCE_PAT",
            help="Confluence Personal Access Token. Required unless CONFLUENCE_PAT is set.",
            rich_help_panel=CONNECTION_HELP_PANEL,
        ),
    ] = None,
    request_delay: Annotated[
        float,
        typer.Option(
            "--request-delay",
            "-d",
            min=0.0,
            help="Minimum delay in seconds between Confluence requests.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = 0.0,
    retry_backoff: Annotated[
        float,
        typer.Option(
            "--retry-backoff",
            "-r",
            min=0.0,
            help="Initial 429 retry backoff in seconds.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = 1.0,
    max_retries: Annotated[
        int,
        typer.Option(
            "--max-retries",
            "-m",
            min=0,
            help="Maximum number of retries for HTTP 429 responses.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = 3,
    verbosity: Annotated[
        str,
        typer.Option(
            "--verbosity",
            "-v",
            help="Progress log verbosity: quiet, normal, or verbose.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
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
                download_html=download_html,
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
        typer.Option(
            "--config",
            "-c",
            exists=True,
            dir_okay=False,
            help="JSON bulk download configuration.",
            rich_help_panel=REQUIRED_HELP_PANEL,
        ),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            file_okay=False,
            help="Directory where PDFs are written.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = Path("."),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Regenerate PDFs even when the manifest version is unchanged.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    group_by_page: Annotated[
        bool,
        typer.Option(
            "--group-by-page/--group-by-space",
            "-g/-G",
            help="Run each configured page as its own group, or combine pages by space and include_children.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = True,
    combine_children: Annotated[
        bool,
        typer.Option(
            "--combine-children/--separate-pages",
            "-C/-p",
            help="When include_children is true, write one combined PDF per configured root.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = True,
    download_html: Annotated[
        bool,
        typer.Option(
            "--download-html",
            help="Also download each Confluence page as a standalone HTML file.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            "-b",
            envvar="CONFLUENCE_BASE_URL",
            help="Confluence base URL. Required unless CONFLUENCE_BASE_URL is set.",
            rich_help_panel=CONNECTION_HELP_PANEL,
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-k",
            envvar="CONFLUENCE_PAT",
            help="Confluence Personal Access Token. Required unless CONFLUENCE_PAT is set.",
            rich_help_panel=CONNECTION_HELP_PANEL,
        ),
    ] = None,
    request_delay: Annotated[
        float,
        typer.Option(
            "--request-delay",
            "-d",
            min=0.0,
            help="Minimum delay in seconds between Confluence requests.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = 0.0,
    retry_backoff: Annotated[
        float,
        typer.Option(
            "--retry-backoff",
            "-r",
            min=0.0,
            help="Initial 429 retry backoff in seconds.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = 1.0,
    max_retries: Annotated[
        int,
        typer.Option(
            "--max-retries",
            "-m",
            min=0,
            help="Maximum number of retries for HTTP 429 responses.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = 3,
    verbosity: Annotated[
        str,
        typer.Option(
            "--verbosity",
            "-v",
            help="Progress log verbosity: quiet, normal, or verbose.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
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
        bulk_config_details = read_bulk_config_details(config)
        requests = bulk_config_details.pages
        output_dir_source = ctx.get_parameter_source("output_dir")
        resolved_output_dir = (
            output_dir
            if output_dir_source is not ParameterSource.DEFAULT
            else bulk_config_details.output_dir or Path(".")
        )

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
                    output_dir=resolved_output_dir,
                    include_children=group.include_children,
                    force=force,
                    skip_unchanged=True,
                    combine_children=combine_children,
                    download_html=download_html,
                )
                _print_summary(summary, resolved_output_dir)
                if summary.failed:
                    failed = True

        if failed:
            raise typer.Exit(code=1)
    except ConfluencePdfError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("list")
def list_space(
    ctx: typer.Context,
    space: Annotated[
        str | None,
        typer.Option("--space", "-s", help="Confluence space key.", rich_help_panel=REQUIRED_HELP_PANEL),
    ] = None,
    depth: Annotated[
        int | None,
        typer.Option(
            "--depth",
            "-d",
            min=1,
            help="Tree depth to list. Root pages are depth 1.",
            rich_help_panel=REQUIRED_HELP_PANEL,
        ),
    ] = None,
    root_title: Annotated[
        str | None,
        typer.Option(
            "--root-title",
            "-r",
            help="Start listing at this page title instead of listing every root page in the space.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = None,
    bulk_config: Annotated[
        Path | None,
        typer.Option(
            "--bulk-config",
            "-c",
            dir_okay=False,
            help="Create or update a JSON bulk config with pages at the final listed depth.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = None,
    bulk_include_children: Annotated[
        bool,
        typer.Option(
            "--bulk-include-children/--no-bulk-include-children",
            "-i/-I",
            help="Set include_children for generated final-depth bulk config entries.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = True,
    ask_download: Annotated[
        bool,
        typer.Option(
            "--ask-download",
            "-a",
            help="After listing pages, prompt to download the listed pages.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="With --ask-download, download listed pages without prompting.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            file_okay=False,
            help="Directory where prompted downloads are written.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = Path("."),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Regenerate prompted downloads even when a valid PDF already exists.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    download_html: Annotated[
        bool,
        typer.Option(
            "--download-html",
            help="With --ask-download, also download each Confluence page as HTML.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    verbosity: Annotated[
        str,
        typer.Option(
            "--verbosity",
            "-v",
            help="Prompted download progress log verbosity: quiet, normal, or verbose.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = "normal",
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            "-b",
            envvar="CONFLUENCE_BASE_URL",
            help="Confluence base URL. Required unless CONFLUENCE_BASE_URL is set.",
            rich_help_panel=CONNECTION_HELP_PANEL,
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-k",
            envvar="CONFLUENCE_PAT",
            help="Confluence Personal Access Token. Required unless CONFLUENCE_PAT is set.",
            rich_help_panel=CONNECTION_HELP_PANEL,
        ),
    ] = None,
    request_delay: Annotated[
        float,
        typer.Option(
            "--request-delay",
            "-D",
            min=0.0,
            help="Minimum delay in seconds between Confluence requests.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = 0.0,
    retry_backoff: Annotated[
        float,
        typer.Option(
            "--retry-backoff",
            "-R",
            min=0.0,
            help="Initial 429 retry backoff in seconds.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = 1.0,
    max_retries: Annotated[
        int,
        typer.Option(
            "--max-retries",
            "-m",
            min=0,
            help="Maximum number of retries for HTTP 429 responses.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
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

            listed_pages = [tree_page.page for tree_page in tree_pages]
            download_confirmed = False
            if ask_download:
                download_confirmed = _prompt_download_pages(
                    client,
                    listed_pages,
                    output_dir=output_dir,
                    force=force,
                    verbosity=verbosity,
                    assume_yes=yes,
                    fallback_space=space,
                    download_html=download_html,
                )

            if bulk_config:
                config_pages = listed_pages if download_confirmed else [
                    tree_page.page for tree_page in tree_pages if tree_page.depth == depth
                ]
                resolved_bulk_config = _generated_bulk_config_path(ctx, bulk_config, output_dir)
                update_bulk_config(
                    resolved_bulk_config,
                    _bulk_requests_from_pages(
                        config_pages,
                        include_children=bulk_include_children,
                        fallback_space=space,
                    ),
                    output_dir=output_dir if download_confirmed else None,
                )
                typer.echo(f"Bulk config updated: {resolved_bulk_config}")
                typer.echo(f"Pages written: {len(config_pages)}")
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
        typer.Option(
            "--space",
            "-s",
            help="Restrict search to this Confluence space key.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-l",
            min=1,
            max=100,
            help="Maximum number of matches to return.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = 10,
    ask_download: Annotated[
        bool,
        typer.Option(
            "--ask-download",
            "-a",
            help="After showing matches, prompt to download the matched pages.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="With --ask-download, download matched pages without prompting.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    bulk_config: Annotated[
        Path | None,
        typer.Option(
            "--bulk-config",
            "-c",
            dir_okay=False,
            help="Create or update a JSON bulk config with the matched pages.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = None,
    bulk_include_children: Annotated[
        bool,
        typer.Option(
            "--bulk-include-children/--no-bulk-include-children",
            "-i/-I",
            help="Set include_children for generated search-result bulk config entries.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            file_okay=False,
            help="Directory where prompted downloads are written.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = Path("."),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Regenerate prompted downloads even when a valid PDF already exists.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    download_html: Annotated[
        bool,
        typer.Option(
            "--download-html",
            help="With --ask-download, also download each Confluence page as HTML.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = False,
    verbosity: Annotated[
        str,
        typer.Option(
            "--verbosity",
            "-v",
            help="Prompted download progress log verbosity: quiet, normal, or verbose.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = "normal",
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            "-b",
            envvar="CONFLUENCE_BASE_URL",
            help="Confluence base URL. Required unless CONFLUENCE_BASE_URL is set.",
            rich_help_panel=CONNECTION_HELP_PANEL,
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-k",
            envvar="CONFLUENCE_PAT",
            help="Confluence Personal Access Token. Required unless CONFLUENCE_PAT is set.",
            rich_help_panel=CONNECTION_HELP_PANEL,
        ),
    ] = None,
    request_delay: Annotated[
        float,
        typer.Option(
            "--request-delay",
            "-d",
            min=0.0,
            help="Minimum delay in seconds between Confluence requests.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = 0.0,
    retry_backoff: Annotated[
        float,
        typer.Option(
            "--retry-backoff",
            "-r",
            min=0.0,
            help="Initial 429 retry backoff in seconds.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
    ] = 1.0,
    max_retries: Annotated[
        int,
        typer.Option(
            "--max-retries",
            "-m",
            min=0,
            help="Maximum number of retries for HTTP 429 responses.",
            rich_help_panel=OPTIONAL_HELP_PANEL,
        ),
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
                ("Page ID", "Space", "Last Edited", "Title", "URL"),
                *[
                    (
                        page.id,
                        page.space,
                        _format_last_edited_age(page.version_when),
                        page.title,
                        page.url,
                    )
                    for page in pages
                ],
            ]
            _print_table(rows)

            download_confirmed = False
            if ask_download:
                download_confirmed = _prompt_download_pages(
                    client,
                    pages,
                    output_dir=output_dir,
                    force=force,
                    verbosity=verbosity,
                    assume_yes=yes,
                    download_html=download_html,
                )

            if bulk_config:
                resolved_bulk_config = _generated_bulk_config_path(ctx, bulk_config, output_dir)
                update_bulk_config(
                    resolved_bulk_config,
                    _bulk_requests_from_pages(
                        pages,
                        include_children=bulk_include_children,
                    ),
                    output_dir=output_dir if download_confirmed else None,
                )
                typer.echo(f"Bulk config updated: {resolved_bulk_config}")
                typer.echo(f"Matched pages written: {len(pages)}")
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
    if summary.html_manifest_path:
        rows.append(("HTML manifest", str(summary.html_manifest_path)))
    _print_box("📊 Group Summary", rows)
    for failure in summary.failures:
        typer.echo(f"- {failure.page.id} {failure.page.title}: {failure.error}", err=True)


def _prompt_download_pages(
    client: ConfluenceClient,
    pages: list[Page],
    *,
    output_dir: Path,
    force: bool,
    verbosity: str,
    assume_yes: bool,
    fallback_space: str | None = None,
    download_html: bool = False,
) -> bool:
    if not pages:
        return False
    if not assume_yes and not typer.confirm(
        f"Download {len(pages)} listed page{'s' if len(pages) != 1 else ''}?",
        default=False,
    ):
        typer.echo("Download skipped.")
        return False

    failed = False
    downloader = PdfDownloader(client, logger=_make_logger(_prompt_download_verbosity(verbosity)))
    for space, titles in _titles_by_space(pages, fallback_space=fallback_space).items():
        summary = downloader.download(
            space_key=space,
            titles=titles,
            output_dir=output_dir,
            include_children=False,
            force=force,
            skip_unchanged=True,
            combine_children=True,
            download_html=download_html,
        )
        _print_summary(summary, output_dir)
        if summary.failed:
            failed = True

    if failed:
        raise typer.Exit(code=1)
    return True


def _generated_bulk_config_path(ctx: typer.Context, bulk_config: Path, output_dir: Path) -> Path:
    output_dir_source = ctx.get_parameter_source("output_dir")
    if output_dir_source is ParameterSource.DEFAULT or bulk_config.is_absolute():
        return bulk_config
    return output_dir / bulk_config


def _titles_by_space(pages: list[Page], *, fallback_space: str | None = None) -> dict[str, list[str]]:
    titles_by_space: dict[str, list[str]] = defaultdict(list)
    for page in pages:
        space = page.space or fallback_space
        if space is None:
            raise ConfigError(f'Page "{page.title}" does not include a space key.')
        if page.title not in titles_by_space[space]:
            titles_by_space[space].append(page.title)
    return dict(titles_by_space)


def _bulk_requests_from_pages(
    pages: list[Page],
    *,
    include_children: bool,
    fallback_space: str | None = None,
) -> list[BulkPageRequest]:
    requests: list[BulkPageRequest] = []
    seen: set[tuple[str, str]] = set()
    for page in pages:
        space = page.space or fallback_space
        if space is None:
            raise ConfigError(f'Page "{page.title}" does not include a space key.')
        key = (space, page.title)
        if key in seen:
            continue
        seen.add(key)
        requests.append(
            BulkPageRequest(
                space=space,
                title=page.title,
                include_children=include_children,
            )
        )
    return requests


def _prompt_download_verbosity(verbosity: str) -> str:
    if verbosity == "quiet":
        return "normal"
    return verbosity


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


def _format_last_edited_age(value: str, *, now: datetime | None = None) -> str:
    if not value:
        return ""
    normalized = value.removesuffix("Z") + "+00:00" if value.endswith("Z") else value
    try:
        edited = datetime.fromisoformat(normalized)
    except ValueError:
        return ""
    if edited.tzinfo is None:
        edited = edited.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    age_days = (reference - edited.astimezone(timezone.utc)).days
    if age_days <= 0:
        return "0d"
    return f"-{age_days}d"


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
