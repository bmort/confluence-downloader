from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

import confluence_downloader.cli as cli
from confluence_downloader.cli import app
from confluence_downloader.downloader import DownloadSummary
from confluence_downloader.models import Page
from confluence_downloader.tree import TreePage


runner = CliRunner()


def test_cli_without_arguments_shows_help() -> None:
    result = runner.invoke(app, [], prog_name="confluence-downloader")

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "confluence-downloader" in result.output
    assert "download" in result.output
    assert "bulk" in result.output
    assert "list" in result.output


def test_cli_accepts_short_help_alias() -> None:
    result = runner.invoke(app, ["-h"], prog_name="confluence-downloader")

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "confluence-downloader" in result.output


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("download", "Download selected Confluence pages"),
        ("bulk", "Download pages from a JSON config"),
        ("list", "List a space page tree"),
        ("search", "Search Confluence page titles"),
    ],
)
def test_cli_subcommands_without_arguments_show_help(command: str, expected: str) -> None:
    result = runner.invoke(app, [command], prog_name="confluence-downloader")

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert f"confluence-downloader {command}" in result.output
    assert expected in result.output


def test_cli_subcommand_accepts_short_help_alias() -> None:
    result = runner.invoke(app, ["download", "-h"], prog_name="confluence-downloader")

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "confluence-downloader download" in result.output
    assert "Download selected Confluence pages" in result.output


def test_cli_help_groups_options_by_purpose() -> None:
    result = runner.invoke(app, ["download", "--help"], prog_name="confluence-downloader")
    compact_output = " ".join(result.output.split())

    assert result.exit_code == 0
    assert "Required options" in compact_output
    assert "Confluence space" in compact_output
    assert "Optional options" in compact_output
    assert "Directory where" in compact_output
    assert "Confluence connection" in compact_output
    assert "--base-url" in compact_output
    assert "--token" in compact_output
    assert "--titles-file is" in compact_output
    assert "CONFLUENCE_BASE_URL is set" in compact_output


class FakeConfluenceClient:
    last_kwargs = {}
    search_calls = []

    def __init__(self, base_url: str, token: str, **kwargs) -> None:
        self.base_url = base_url
        self.token = token
        FakeConfluenceClient.last_kwargs = kwargs

    def __enter__(self) -> "FakeConfluenceClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def search_pages_by_title(self, query: str, *, space_key: str | None = None, limit: int = 10) -> list[Page]:
        FakeConfluenceClient.search_calls.append(
            {"query": query, "space_key": space_key, "limit": limit}
        )
        return [
            Page(
                id="123",
                title="Architecture Overview",
                url="https://confluence.example.test/display/DOC/Architecture+Overview",
                space="DOC",
                version_when="2026-05-01T08:30:00.000Z",
            )
        ]


class FakeDownloader:
    last_call = None
    calls = []
    init_kwargs = []

    def __init__(self, client: FakeConfluenceClient, **kwargs) -> None:
        self.client = client
        FakeDownloader.init_kwargs.append(kwargs)

    def download(self, **kwargs) -> DownloadSummary:
        FakeDownloader.last_call = kwargs
        FakeDownloader.calls.append(kwargs)
        return DownloadSummary(roots_requested=len(kwargs["titles"]), pages_found=len(kwargs["titles"]))


def test_cli_search_uses_query_and_space_filter(monkeypatch) -> None:
    FakeConfluenceClient.search_calls = []
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)

    result = runner.invoke(
        app,
        [
            "search",
            "arch overview",
            "-s",
            "DOC",
            "-l",
            "5",
        ],
    )

    assert result.exit_code == 0
    assert FakeConfluenceClient.search_calls == [
        {"query": "arch overview", "space_key": "DOC", "limit": 5}
    ]
    assert "Page ID" in result.output
    assert "Last Edited" in result.output
    assert "2026-05-01T08:30:00.000Z" not in result.output
    assert "Architecture Overview" in result.output
    assert "https://confluence.example.test/display/DOC/Architecture+Overview" in result.output


def test_format_last_edited_age_reports_days_old() -> None:
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)

    assert cli._format_last_edited_age("2026-04-12T12:00:00.000Z", now=now) == "-30d"


def test_format_last_edited_age_handles_missing_invalid_and_future_values() -> None:
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    future = now + timedelta(days=1)

    assert cli._format_last_edited_age("", now=now) == ""
    assert cli._format_last_edited_age("not-a-date", now=now) == ""
    assert cli._format_last_edited_age(future.isoformat(), now=now) == "0d"


def test_cli_search_reports_no_matches(monkeypatch) -> None:
    class NoMatchClient(FakeConfluenceClient):
        def search_pages_by_title(self, query: str, *, space_key: str | None = None, limit: int = 10) -> list[Page]:
            return []

    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", NoMatchClient)

    result = runner.invoke(app, ["search", "missing", "--space", "DOC"])

    assert result.exit_code == 0
    assert 'No matching pages found for "missing" in space DOC.' in result.output


def test_cli_search_can_prompt_to_download_matches(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    FakeDownloader.init_kwargs = []
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)

    result = runner.invoke(
        app,
        [
            "search",
            "arch overview",
            "--space",
            "DOC",
            "-a",
            "--output-dir",
            str(tmp_path),
            "--force",
        ],
        input="y\n",
    )

    assert result.exit_code == 0
    assert "Download 1 listed page?" in result.output
    assert FakeDownloader.calls == [
        {
            "space_key": "DOC",
            "titles": ["Architecture Overview"],
            "output_dir": tmp_path,
            "include_children": False,
            "force": True,
            "skip_unchanged": True,
            "combine_children": True,
            "download_html": False,
        }
    ]
    assert len(FakeDownloader.init_kwargs) == 1
    assert callable(FakeDownloader.init_kwargs[0]["logger"])


def test_cli_search_prompt_can_skip_download(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    FakeDownloader.init_kwargs = []
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)

    result = runner.invoke(
        app,
        [
            "search",
            "arch overview",
            "--ask-download",
            "--output-dir",
            str(tmp_path),
        ],
        input="n\n",
    )

    assert result.exit_code == 0
    assert "Download skipped." in result.output
    assert FakeDownloader.calls == []
    assert FakeDownloader.init_kwargs == []


def test_cli_search_can_auto_confirm_prompted_download(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)

    result = runner.invoke(
        app,
        [
            "search",
            "arch overview",
            "--ask-download",
            "--yes",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "Download 1 listed page?" not in result.output
    assert FakeDownloader.calls == [
        {
            "space_key": "DOC",
            "titles": ["Architecture Overview"],
            "output_dir": tmp_path,
            "include_children": False,
            "force": False,
            "skip_unchanged": True,
            "combine_children": True,
            "download_html": False,
        }
    ]


def test_cli_search_prompt_raises_quiet_verbosity_to_normal(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    FakeDownloader.init_kwargs = []
    made_loggers = []
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)

    def fake_make_logger(verbosity: str):
        made_loggers.append(verbosity)
        return f"logger:{verbosity}"

    monkeypatch.setattr(cli, "_make_logger", fake_make_logger)

    result = runner.invoke(
        app,
        [
            "search",
            "arch overview",
            "-a",
            "--output-dir",
            str(tmp_path),
            "--verbosity",
            "quiet",
        ],
        input="y\n",
    )

    assert result.exit_code == 0
    assert FakeDownloader.calls
    assert made_loggers == ["normal"]
    assert FakeDownloader.init_kwargs == [{"logger": "logger:normal"}]


def test_cli_search_updates_bulk_config(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / "pages.json"
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)

    result = runner.invoke(
        app,
        [
            "search",
            "arch overview",
            "--space",
            "DOC",
            "--bulk-config",
            str(config),
            "--bulk-include-children",
        ],
    )

    config_text = config.read_text(encoding="utf-8")
    assert result.exit_code == 0
    assert "Bulk config updated:" in result.output
    assert "Matched pages written: 1" in result.output
    assert '"space": "DOC"' in config_text
    assert '"title": "Architecture Overview"' in config_text
    assert '"include_children": true' in config_text


def test_cli_search_writes_output_dir_to_bulk_config_after_prompted_download(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    output_dir = tmp_path / "pdfs"
    config = output_dir / "pages.json"
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)

    result = runner.invoke(
        app,
        [
            "search",
            "arch overview",
            "--space",
            "DOC",
            "--ask-download",
            "--bulk-config",
            "pages.json",
            "--output-dir",
            str(output_dir),
        ],
        input="y\n",
    )

    config_text = config.read_text(encoding="utf-8")
    assert result.exit_code == 0
    assert FakeDownloader.calls
    assert f'"output_dir": "{output_dir}"' in config_text


def test_cli_search_writes_relative_bulk_config_under_output_dir(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "pdfs"
    config = output_dir / "pages.json"
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)

    result = runner.invoke(
        app,
        [
            "search",
            "arch overview",
            "--bulk-config",
            "pages.json",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert f"Bulk config updated: {config}" in result.output
    assert config.exists()


def test_cli_uses_env_config_and_repeated_titles(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
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
        "combine_children": True,
        "download_html": False,
    }
    assert "Pages found: 2" in result.output
    assert "📊 Group Summary" in result.output
    assert "┌─" in result.output
    assert "└" in result.output


def test_cli_download_can_request_html_pages(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
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
            "--download-html",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert FakeDownloader.last_call["download_html"] is True


def test_cli_option_config_beats_env(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://env.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    created = {}

    class CapturingClient(FakeConfluenceClient):
        def __init__(self, base_url: str, token: str, **kwargs) -> None:
            super().__init__(base_url, token, **kwargs)
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
            "--request-delay",
            "0.25",
            "--retry-backoff",
            "2",
            "--max-retries",
            "5",
        ],
    )

    assert result.exit_code == 0
    assert created == {
        "base_url": "https://cli.example.test/confluence",
        "token": "cli-token",
    }
    assert FakeConfluenceClient.last_kwargs == {
        "request_delay": 0.25,
        "retry_backoff": 2.0,
        "max_retries": 5,
    }


def test_cli_download_accepts_short_option_aliases(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)

    result = runner.invoke(
        app,
        [
            "download",
            "-s",
            "DOC",
            "-t",
            "Root",
            "-o",
            str(tmp_path),
            "-b",
            "https://cli.example.test/confluence",
            "-k",
            "cli-token",
            "-d",
            "0.25",
            "-r",
            "2",
            "-m",
            "5",
            "-i",
            "-p",
            "-f",
            "-v",
            "quiet",
        ],
    )

    assert result.exit_code == 0
    assert FakeDownloader.last_call == {
        "space_key": "DOC",
        "titles": ["Root"],
        "output_dir": tmp_path,
        "include_children": True,
        "force": True,
        "combine_children": False,
        "download_html": False,
    }
    assert FakeConfluenceClient.last_kwargs == {
        "request_delay": 0.25,
        "retry_backoff": 2.0,
        "max_retries": 5,
    }


def test_cli_bulk_uses_config_and_skips_unchanged(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    config = tmp_path / "pages.json"
    config.write_text(
        """
        {
          "include_children": true,
          "pages": [
            {"space": "DOC", "title": "Root"},
            {"space": "DOC", "title": "Other", "include_children": false}
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)

    result = runner.invoke(
        app,
        [
            "bulk",
            "--config",
            str(config),
            "--output-dir",
            str(tmp_path / "pdfs"),
        ],
    )

    assert result.exit_code == 0
    assert "📋 Bulk config pages: 2" in result.output
    assert "Download groups: 2" in result.output
    assert "Grouping: page" in result.output
    assert "📦 Group 1/2: space=DOC include_children=True roots=1" in result.output
    assert FakeDownloader.calls == [
        {
            "space_key": "DOC",
            "titles": ["Root"],
            "output_dir": tmp_path / "pdfs",
            "include_children": True,
            "force": False,
            "skip_unchanged": True,
            "combine_children": True,
            "download_html": False,
        },
        {
            "space_key": "DOC",
            "titles": ["Other"],
            "output_dir": tmp_path / "pdfs",
            "include_children": False,
            "force": False,
            "skip_unchanged": True,
            "combine_children": True,
            "download_html": False,
        },
    ]


def test_cli_bulk_uses_config_output_dir_when_option_is_omitted(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    config = tmp_path / "pages.json"
    output_dir = tmp_path / "pdfs"
    config.write_text(
        f"""
        {{
          "output_dir": "{output_dir}",
          "pages": [
            {{"space": "DOC", "title": "Root", "include_children": true}}
          ]
        }}
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)

    result = runner.invoke(app, ["bulk", "--config", str(config)])

    assert result.exit_code == 0
    assert FakeDownloader.calls == [
        {
            "space_key": "DOC",
            "titles": ["Root"],
            "output_dir": output_dir,
            "include_children": True,
            "force": False,
            "skip_unchanged": True,
            "combine_children": True,
            "download_html": False,
        }
    ]


def test_cli_bulk_quiet_suppresses_progress_logs(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    config = tmp_path / "pages.json"
    config.write_text(
        '{"pages": [{"space": "DOC", "title": "Root", "include_children": true}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)

    result = runner.invoke(
        app,
        [
            "bulk",
            "--config",
            str(config),
            "--verbosity",
            "quiet",
        ],
    )

    assert result.exit_code == 0
    assert "Bulk config pages" not in result.output
    assert "Roots requested: 1" in result.output


def test_cli_bulk_can_group_by_space(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    config = tmp_path / "pages.json"
    config.write_text(
        """
        {
          "pages": [
            {"space": "DOC", "title": "Root", "include_children": true},
            {"space": "DOC", "title": "Other", "include_children": true}
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)

    result = runner.invoke(
        app,
        [
            "bulk",
            "--config",
            str(config),
            "--group-by-space",
        ],
    )

    assert result.exit_code == 0
    assert "Download groups: 1" in result.output
    assert "Grouping: space" in result.output
    assert FakeDownloader.calls == [
        {
            "space_key": "DOC",
            "titles": ["Root", "Other"],
            "output_dir": Path("."),
            "include_children": True,
            "force": False,
            "skip_unchanged": True,
            "combine_children": True,
            "download_html": False,
        }
    ]


def test_cli_bulk_accepts_short_option_aliases(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    config = tmp_path / "pages.json"
    config.write_text(
        '{"pages": [{"space": "DOC", "title": "Root", "include_children": true}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)

    result = runner.invoke(
        app,
        [
            "bulk",
            "-c",
            str(config),
            "-o",
            str(tmp_path / "out"),
            "-b",
            "https://cli.example.test/confluence",
            "-k",
            "cli-token",
            "-d",
            "0.25",
            "-r",
            "2",
            "-m",
            "5",
            "-G",
            "-p",
            "-f",
            "-v",
            "quiet",
        ],
    )

    assert result.exit_code == 0
    assert FakeDownloader.calls == [
        {
            "space_key": "DOC",
            "titles": ["Root"],
            "output_dir": tmp_path / "out",
            "include_children": True,
            "force": True,
            "skip_unchanged": True,
            "combine_children": False,
            "download_html": False,
        }
    ]


def test_cli_list_space_updates_bulk_config(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / "pages.json"
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(
        cli,
        "list_space_tree",
        lambda client, space_key, max_depth, root_title=None: [
            TreePage(page=Page(id="1", title="Root", version=1), depth=1, path=("Root",)),
            TreePage(page=Page(id="2", title="Child [2]", version=3), depth=2, path=("Root", "Child [2]")),
        ],
    )

    result = runner.invoke(
        app,
        [
            "list",
            "--space",
            "DOC",
            "--depth",
            "2",
            "--bulk-config",
            str(config),
            "--no-bulk-include-children",
        ],
    )

    assert result.exit_code == 0
    assert '- "Root" | id=1 version=1' in result.output
    assert '  - "Child [2]" | id=2 version=3' in result.output
    assert '"space": "DOC"' in config.read_text(encoding="utf-8")
    assert '"title": "Child [2]"' in config.read_text(encoding="utf-8")
    assert '"include_children": false' in config.read_text(encoding="utf-8")


def test_cli_list_space_writes_relative_bulk_config_under_output_dir(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "pdfs"
    config = output_dir / "pages.json"
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(
        cli,
        "list_space_tree",
        lambda client, space_key, max_depth, root_title=None: [
            TreePage(page=Page(id="2", title="Child"), depth=1, path=("Child",)),
        ],
    )

    result = runner.invoke(
        app,
        [
            "list",
            "--space",
            "DOC",
            "--depth",
            "1",
            "--bulk-config",
            "pages.json",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert f"Bulk config updated: {config}" in result.output
    assert config.exists()


def test_cli_list_space_prompted_bulk_config_uses_downloaded_listed_pages(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    output_dir = tmp_path / "updates"
    config = output_dir / "pages.json"
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)
    monkeypatch.setattr(
        cli,
        "list_space_tree",
        lambda client, space_key, max_depth, root_title=None: [
            TreePage(page=Page(id="1", title="Root"), depth=1, path=("Root",)),
            TreePage(page=Page(id="2", title="Child"), depth=2, path=("Root", "Child")),
        ],
    )

    result = runner.invoke(
        app,
        [
            "list",
            "-s",
            "DOC",
            "-d",
            "3",
            "--ask-download",
            "-y",
            "-o",
            str(output_dir),
            "-c",
            "pages.json",
        ],
    )

    config_text = config.read_text(encoding="utf-8")
    assert result.exit_code == 0
    assert "Pages written: 2" in result.output
    assert '"output_dir": "' in config_text
    assert '"title": "Root"' in config_text
    assert '"title": "Child"' in config_text
    assert FakeDownloader.calls == [
        {
            "space_key": "DOC",
            "titles": ["Root", "Child"],
            "output_dir": output_dir,
            "include_children": False,
            "force": False,
            "skip_unchanged": True,
            "combine_children": True,
            "download_html": False,
        }
    ]


def test_cli_list_space_accepts_root_title(monkeypatch) -> None:
    captured = {}
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)

    def fake_list_space_tree(client, space_key, max_depth, root_title=None):
        captured["space_key"] = space_key
        captured["max_depth"] = max_depth
        captured["root_title"] = root_title
        return [TreePage(page=Page(id="2", title="Child"), depth=1, path=("Child",))]

    monkeypatch.setattr(cli, "list_space_tree", fake_list_space_tree)

    result = runner.invoke(
        app,
        [
            "list",
            "-s",
            "DOC",
            "-d",
            "1",
            "-r",
            "Child",
        ],
    )

    assert result.exit_code == 0
    assert captured == {"space_key": "DOC", "max_depth": 1, "root_title": "Child"}


def test_cli_list_space_can_prompt_to_download_listed_pages(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    FakeDownloader.init_kwargs = []
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)
    monkeypatch.setattr(
        cli,
        "list_space_tree",
        lambda client, space_key, max_depth, root_title=None: [
            TreePage(page=Page(id="1", title="Root"), depth=1, path=("Root",)),
            TreePage(page=Page(id="2", title="Child"), depth=2, path=("Root", "Child")),
        ],
    )

    result = runner.invoke(
        app,
        [
            "list",
            "--space",
            "DOC",
            "--depth",
            "2",
            "-a",
            "--output-dir",
            str(tmp_path),
            "--verbosity",
            "verbose",
        ],
        input="y\n",
    )

    assert result.exit_code == 0
    assert "Download 2 listed pages?" in result.output
    assert FakeDownloader.calls == [
        {
            "space_key": "DOC",
            "titles": ["Root", "Child"],
            "output_dir": tmp_path,
            "include_children": False,
            "force": False,
            "skip_unchanged": True,
            "combine_children": True,
            "download_html": False,
        }
    ]
    assert len(FakeDownloader.init_kwargs) == 1
    assert callable(FakeDownloader.init_kwargs[0]["logger"])


def test_cli_list_space_can_auto_confirm_prompted_download(monkeypatch, tmp_path: Path) -> None:
    FakeDownloader.calls = []
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.example.test")
    monkeypatch.setenv("CONFLUENCE_PAT", "env-token")
    monkeypatch.setattr(cli, "ConfluenceClient", FakeConfluenceClient)
    monkeypatch.setattr(cli, "PdfDownloader", FakeDownloader)
    monkeypatch.setattr(
        cli,
        "list_space_tree",
        lambda client, space_key, max_depth, root_title=None: [
            TreePage(page=Page(id="1", title="Root"), depth=1, path=("Root",)),
        ],
    )

    result = runner.invoke(
        app,
        [
            "list",
            "--space",
            "DOC",
            "--depth",
            "1",
            "--ask-download",
            "-y",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "Download 1 listed page?" not in result.output
    assert FakeDownloader.calls == [
        {
            "space_key": "DOC",
            "titles": ["Root"],
            "output_dir": tmp_path,
            "include_children": False,
            "force": False,
            "skip_unchanged": True,
            "combine_children": True,
            "download_html": False,
        }
    ]


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
