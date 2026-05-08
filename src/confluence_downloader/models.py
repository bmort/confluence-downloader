from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    id: str
    title: str
    url: str = ""
    version: int | None = None
    version_when: str = ""
