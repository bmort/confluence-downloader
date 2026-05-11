from pathlib import Path

import pytest

from confluence_downloader.config import BulkPageRequest, read_bulk_config, read_bulk_config_details, update_bulk_config
from confluence_downloader.errors import ConfigError


def test_read_bulk_config_accepts_pages_object(tmp_path: Path) -> None:
    config = tmp_path / "pages.json"
    config.write_text(
        """
        {
          "include_children": true,
          "pages": [
            {"space": "DOC", "title": "Root"},
            {"space": "OPS", "title": "Runbook", "include_children": false}
          ]
        }
        """,
        encoding="utf-8",
    )

    assert read_bulk_config(config) == [
        BulkPageRequest(space="DOC", title="Root", include_children=True),
        BulkPageRequest(space="OPS", title="Runbook", include_children=False),
    ]


def test_read_bulk_config_details_accepts_output_dir(tmp_path: Path) -> None:
    config = tmp_path / "pages.json"
    config.write_text(
        """
        {
          "output_dir": "pdfs",
          "pages": [
            {"space": "DOC", "title": "Root"}
          ]
        }
        """,
        encoding="utf-8",
    )

    details = read_bulk_config_details(config)

    assert details.output_dir == Path("pdfs")
    assert details.pages == [
        BulkPageRequest(space="DOC", title="Root", include_children=False),
    ]


def test_read_bulk_config_accepts_top_level_array(tmp_path: Path) -> None:
    config = tmp_path / "pages.json"
    config.write_text('[{"space": "DOC", "title": "Root"}]', encoding="utf-8")

    assert read_bulk_config(config) == [
        BulkPageRequest(space="DOC", title="Root", include_children=False),
    ]


def test_read_bulk_config_requires_title_and_space(tmp_path: Path) -> None:
    config = tmp_path / "pages.json"
    config.write_text('[{"space": "DOC"}]', encoding="utf-8")

    with pytest.raises(ConfigError, match="missing a non-empty title"):
        read_bulk_config(config)


def test_update_bulk_config_creates_file(tmp_path: Path) -> None:
    config = tmp_path / "pages.json"

    update_bulk_config(
        config,
        [
            BulkPageRequest(space="DOC", title="Root", include_children=True),
            BulkPageRequest(space="OPS", title="Runbook", include_children=False),
        ],
    )

    assert read_bulk_config(config) == [
        BulkPageRequest(space="DOC", title="Root", include_children=True),
        BulkPageRequest(space="OPS", title="Runbook", include_children=False),
    ]


def test_update_bulk_config_can_write_output_dir(tmp_path: Path) -> None:
    config = tmp_path / "pages.json"

    update_bulk_config(
        config,
        [BulkPageRequest(space="DOC", title="Root", include_children=False)],
        output_dir=tmp_path / "pdfs",
    )

    config_text = config.read_text(encoding="utf-8")
    assert f'"output_dir": "{tmp_path / "pdfs"}"' in config_text
    assert read_bulk_config_details(config).output_dir == tmp_path / "pdfs"


def test_update_bulk_config_updates_existing_page(tmp_path: Path) -> None:
    config = tmp_path / "pages.json"
    config.write_text(
        '{"include_children": false, "pages": [{"space": "DOC", "title": "Root", "include_children": false}]}',
        encoding="utf-8",
    )

    update_bulk_config(
        config,
        [BulkPageRequest(space="DOC", title="Root", include_children=True)],
    )

    assert read_bulk_config(config) == [
        BulkPageRequest(space="DOC", title="Root", include_children=True),
    ]
