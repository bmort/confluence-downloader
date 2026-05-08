from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from .errors import ConfigError


def normalize_base_url(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("--base-url must be an absolute http(s) URL")
    return cleaned


def read_titles_file(path: Path) -> list[str]:
    titles: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        title = raw_line.strip()
        if title and not title.startswith("#"):
            titles.append(title)
    return titles


def merge_titles(repeated_titles: list[str] | None, titles_file: Path | None) -> list[str]:
    titles: list[str] = []
    if repeated_titles:
        titles.extend(title.strip() for title in repeated_titles if title.strip())
    if titles_file:
        titles.extend(read_titles_file(titles_file))
    seen: set[str] = set()
    unique_titles: list[str] = []
    for title in titles:
        if title not in seen:
            unique_titles.append(title)
            seen.add(title)
    return unique_titles


def slugify_title(title: str, max_length: int = 80) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = "untitled"
    return slug[:max_length].rstrip("-") or "untitled"
