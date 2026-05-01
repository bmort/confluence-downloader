from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError


@dataclass(frozen=True)
class BulkPageRequest:
    space: str
    title: str
    include_children: bool


def read_bulk_config(path: Path) -> list[BulkPageRequest]:
    raw_config = _read_raw_config(path)
    raw_pages, default_include_children = _extract_pages(raw_config, allow_empty=False)

    requests: list[BulkPageRequest] = []
    for index, raw_page in enumerate(raw_pages, start=1):
        requests.append(_parse_page_request(raw_page, index, default_include_children))
    return requests


def update_bulk_config(path: Path, requests: list[BulkPageRequest]) -> None:
    if path.exists():
        raw_config = _read_raw_config(path)
        raw_pages, default_include_children = _extract_pages(raw_config, allow_empty=True)
    else:
        raw_config = {"include_children": False, "pages": []}
        raw_pages = raw_config["pages"]
        default_include_children = False

    pages_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for index, raw_page in enumerate(raw_pages, start=1):
        parsed = _parse_page_request(raw_page, index, default_include_children)
        pages_by_key[(parsed.space, parsed.title)] = {
            "space": parsed.space,
            "title": parsed.title,
            "include_children": parsed.include_children,
        }

    for request in requests:
        pages_by_key[(request.space, request.title)] = {
            "space": request.space,
            "title": request.title,
            "include_children": request.include_children,
        }

    updated_pages = sorted(pages_by_key.values(), key=lambda item: (item["space"], item["title"]))
    if isinstance(raw_config, list):
        output: Any = updated_pages
    else:
        output = dict(raw_config)
        output["pages"] = updated_pages

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _read_raw_config(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Could not read bulk config {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Bulk config {path} is not valid JSON: {exc}") from exc


def _extract_pages(raw_config: Any, *, allow_empty: bool) -> tuple[list[Any], bool]:
    default_include_children = False
    if isinstance(raw_config, list):
        raw_pages = raw_config
    elif isinstance(raw_config, dict):
        default_include_children = bool(raw_config.get("include_children", False))
        raw_pages = raw_config.get("pages")
    else:
        raise ConfigError("Bulk config must be a JSON object or array.")

    if not isinstance(raw_pages, list) or (not raw_pages and not allow_empty):
        raise ConfigError("Bulk config must contain at least one page entry.")
    return raw_pages, default_include_children


def _parse_page_request(
    raw_page: Any,
    index: int,
    default_include_children: bool,
) -> BulkPageRequest:
    if not isinstance(raw_page, dict):
        raise ConfigError(f"Bulk config page #{index} must be an object.")

    space = str(raw_page.get("space", "")).strip()
    title = str(raw_page.get("title", "")).strip()
    if not space:
        raise ConfigError(f"Bulk config page #{index} is missing a non-empty space.")
    if not title:
        raise ConfigError(f"Bulk config page #{index} is missing a non-empty title.")

    include_children = raw_page.get("include_children", default_include_children)
    if not isinstance(include_children, bool):
        raise ConfigError(f"Bulk config page #{index} include_children must be true or false.")

    return BulkPageRequest(space=space, title=title, include_children=include_children)
