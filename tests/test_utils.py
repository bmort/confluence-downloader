from pathlib import Path

import pytest

from confluence_pdf.errors import ConfigError
from confluence_pdf.utils import merge_titles, normalize_base_url, slugify_title


def test_normalize_base_url_removes_trailing_slashes() -> None:
    assert normalize_base_url("https://example.test/confluence//") == "https://example.test/confluence"


def test_normalize_base_url_requires_absolute_http_url() -> None:
    with pytest.raises(ConfigError):
        normalize_base_url("example.test/confluence")


def test_merge_titles_deduplicates_repeated_and_file_titles(tmp_path: Path) -> None:
    titles_file = tmp_path / "titles.txt"
    titles_file.write_text("Beta\n# ignored\nAlpha\n\nGamma\n", encoding="utf-8")

    assert merge_titles(["Alpha", "Beta"], titles_file) == ["Alpha", "Beta", "Gamma"]


def test_slugify_title_is_filesystem_safe() -> None:
    assert slugify_title("Architecture: Overview / v2?") == "architecture-overview-v2"


def test_slugify_title_handles_symbol_only_titles() -> None:
    assert slugify_title("???") == "untitled"
