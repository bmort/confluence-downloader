from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Space:
    key: str
    name: str = ""
    url: str = ""


@dataclass(frozen=True)
class ExternalResource:
    """A resource embedded on a page but hosted outside Confluence."""

    kind: str
    url: str


@dataclass(frozen=True)
class Attachment:
    id: str
    title: str
    media_type: str = ""
    file_size: int | None = None
    version: int | None = None
    download_path: str = ""


@dataclass(frozen=True)
class Page:
    id: str
    title: str
    url: str = ""
    version: int | None = None
    version_when: str = ""
    space: str = ""
