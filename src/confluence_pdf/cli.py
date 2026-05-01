from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from .client import ConfluenceClient
from .downloader import PdfDownloader
from .errors import ConfigError, ConfluencePdfError
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
) -> None:
    """Download selected Confluence pages as individual PDF files."""
    try:
        resolved_base_url = _required_base_url(base_url)
        resolved_token = _required_token(token)
        titles = merge_titles(title, titles_file)
        if not titles:
            raise ConfigError("Provide at least one --title or --titles-file entry.")

        with ConfluenceClient(resolved_base_url, resolved_token) as client:
            downloader = PdfDownloader(client)
            summary = downloader.download(
                space_key=space,
                titles=titles,
                output_dir=output_dir,
                include_children=include_children,
                force=force,
            )

        _print_summary(summary, output_dir / space)
        if summary.failed:
            raise typer.Exit(code=1)
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
    typer.echo(f"Roots requested: {summary.roots_requested}")
    typer.echo(f"Pages found: {summary.pages_found}")
    typer.echo(f"Exported: {len(summary.exported)}")
    typer.echo(f"Skipped existing: {len(summary.skipped)}")
    typer.echo(f"Failed: {summary.failed}")
    typer.echo(f"Output directory: {output_path}")
    if summary.manifest_path:
        typer.echo(f"Manifest: {summary.manifest_path}")
    for failure in summary.failures:
        typer.echo(f"- {failure.page.id} {failure.page.title}: {failure.error}", err=True)


if __name__ == "__main__":
    app()
