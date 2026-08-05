from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .config import BulkPageRequest
from .errors import ConfigError
from .models import Page


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


def titles_by_space(pages: list[Page], *, fallback_space: str | None = None) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for page in pages:
        space = page.space or fallback_space
        if space is None:
            raise ConfigError(f'Page "{page.title}" does not include a space key.')
        if page.title not in grouped[space]:
            grouped[space].append(page.title)
    return dict(grouped)


def bulk_requests_from_pages(
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


def format_last_edited_age(value: str, *, now: datetime | None = None) -> str:
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


_OSC8_LINK_RE = re.compile(r"\x1b\]8;;[^\x1b]*\x1b\\")


def hyperlink(text: str, url: str) -> str:
    """Wrap text in an OSC 8 terminal hyperlink; plain text when no URL is known."""
    if not url:
        return text
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"


def strip_hyperlinks(message: str) -> str:
    return _OSC8_LINK_RE.sub("", message)


def decorate_log(message: str) -> str:
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
    elif lower.startswith("cancelled"):
        icon = "🛑"
    elif lower.startswith("starting"):
        icon = "🚀"
    else:
        icon = "ℹ️"
    return f"{icon} {message}"


def sanitize_filename(name: str) -> str:
    cleaned = name.replace("/", "_").replace("\\", "_").replace("\0", "")
    cleaned = cleaned.strip().strip(".")
    return cleaned or "attachment"


def format_file_size(size: int | None) -> str:
    if size is None:
        return "unknown size"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def slugify_title(title: str, max_length: int = 80) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = "untitled"
    return slug[:max_length].rstrip("-") or "untitled"
