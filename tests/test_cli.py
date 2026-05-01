from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import confluence_pdf.cli as cli
from confluence_pdf.cli import app
from confluence_pdf.downloader import DownloadSummary


runner = CliRunner()


class FakeConfluenceClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url
        self.token = token

    def __enter__(self) -> "FakeConfluenceClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class FakeDownloader:
    last_call = None

    def __init__(self, client: FakeConfluenceClient) -> None:
        self.client = client

    def download(self, **kwargs) -> DownloadSummary:
        FakeDownloader.last_call = kwargs
        return DownloadSummary(roots_requested=len(kwargs["titles"]), pages_found=len(kwargs["titles"]))


def test_cli_uses_env_config_and_repeated_titles(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test/confluence/")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)

    result = runner.invoke(
        app,
        [
            "download",
            "--space",
            "DOC",
            "--title",
            "Root",
            "--title",
            "Other",
            "--include-children",
            "--force",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert FakeDownloader.last_call == {
        "space_key": "DOC",
        "titles": ["Root", "Other"],
        "output_dir": tmp_path,
        "include_children": True,
        "force": True,
    }
    assert "Pages found: 2" in result.output


def test_cli_option_config_beats_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://env.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    created = {}

    class CapturingClient(FakeConfluenceClient):
        def __init__(self, base_url: str, token: str) -> None:
            super().__init__(base_url, token)
            created["base_url"] = base_url
            created["token"] = token

    monkeypatch.setattr(cli, "ConfluenceClient", CapturingClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)

    result = runner.invoke(
        app,
        [
            "download",
            "--space",
            "DOC",
            "--title",
            "Root",
            "--output-dir",
            str(tmp_path),
            "--base-url",
            "https://cli.example.test/confluence",
            "--token",
            "cli-token",
        ],
    )

    assert result.exit_code == 0
    assert created == {
        "base_url": "https://cli.example.test/confluence",
        "token": "cli-token",
    }


def test_cli_requires_title_or_titles_file(monkeypatch) -> None:
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")

    result = runner.invoke(app, ["download", "--space", "DOC"])

    assert result.exit_code == 1
    assert "Provide at least one --title or --titles-file entry." in result.output


def test_cli_requires_base_url(monkeypatch) -> None:
    monkeypatch.delenv("CONFLUENCE_BASE_URL", raising=False)
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")

    result = runner.invoke(app, ["download", "--space", "DOC", "--title", "Root"])

    assert result.exit_code == 1
    assert "Provide --base-url or set CONFLUENCE_BASE_URL." in result.output
