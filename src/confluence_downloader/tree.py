from __future__ import annotations

from dataclasses import dataclass

from .client import ConfluenceClient
from .models import Page


@dataclass(frozen=True)
class TreePage:
    page: Page
    depth: int
    path: tuple[str, ...]


def list_space_tree(
    client: ConfluenceClient,
    *,
    space_key: str,
    max_depth: int,
    root_title: str | None = None,
) -> list[TreePage]:
    if max_depth < 1:
        raise ValueError("max_depth must be at least 1")

    tree_pages: list[TreePage] = []
    roots = [client.resolve_page_by_title(space_key, root_title)] if root_title else client.list_space_root_pages(space_key)
    for root in roots:
        _append_tree_page(
            client,
            page=root,
            depth=1,
            max_depth=max_depth,
            path=(root.title,),
            tree_pages=tree_pages,
        )
    return tree_pages


def _append_tree_page(
    client: ConfluenceClient,
    *,
    page: Page,
    depth: int,
    max_depth: int,
    path: tuple[str, ...],
    tree_pages: list[TreePage],
) -> None:
    tree_pages.append(TreePage(page=page, depth=depth, path=path))
    if depth >= max_depth:
        return

    for child in client.list_child_pages(page.id):
        _append_tree_page(
            client,
            page=child,
            depth=depth + 1,
            max_depth=max_depth,
            path=(*path, child.title),
            tree_pages=tree_pages,
        )
