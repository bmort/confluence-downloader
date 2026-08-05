from __future__ import annotations

import json
from pathlib import Path

from textual.widgets import Input, SelectionList, Tree

from confluence_downloader.downloader import DownloadSummary
from confluence_downloader.models import Page, Space
from confluence_downloader.tui import ConfluenceTui
from confluence_downloader.tui.search import SearchScreen

ROOT = Page(
    id="1",
    title="Root",
    url="https://confluence.test/pages/1",
    space="DOC",
    version=5,
    version_when="2026-05-01T08:30:00.000Z",
)
OTHER = Page(id="2", title="Other", url="https://confluence.test/pages/2", space="DOC", version=1)
CHILD = Page(id="3", title="Child", url="https://confluence.test/pages/3", version=2)
GRANDCHILD = Page(id="4", title="Grandchild", url="https://confluence.test/pages/4", version=1)


class FakeClient:
    def __init__(self) -> None:
        self.search_results: list[Page] = []

    def search_pages_by_title(self, query: str, *, space_key=None, limit=10) -> list[Page]:
        return self.search_results

    def list_spaces(self, *, page_size: int = 50) -> list[Space]:
        return [Space(key="DOC", name="Documentation"), Space(key="ENG", name="Engineering")]

    def list_space_root_pages(self, space_key: str, *, page_size: int = 50) -> list[Page]:
        return [ROOT, OTHER]

    def list_child_pages(self, page_id: str, *, page_size: int = 50) -> list[Page]:
        return {"1": [CHILD, GRANDCHILD], "2": [], "3": [], "4": []}[page_id]

    def iter_descendants(self, root: Page, *, page_size: int = 50) -> list[Page]:
        if root.id == "1":
            return [CHILD, GRANDCHILD]
        return []

    def resolve_page_by_title(self, space_key: str, title: str) -> Page:
        return {"Root": ROOT, "Other": OTHER}[title]


class FakeDownloader:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def download(self, **kwargs) -> DownloadSummary:
        self.calls.append(kwargs)
        return DownloadSummary(
            roots_requested=len(kwargs["titles"]),
            pages_found=len(kwargs["titles"]),
        )


def make_app(tmp_path: Path) -> tuple[ConfluenceTui, FakeClient, FakeDownloader]:
    client = FakeClient()
    downloader = FakeDownloader()
    app = ConfluenceTui(
        client=client,  # type: ignore[arg-type]
        output_dir=tmp_path,
        downloader_factory=lambda _client, _logger, _should_stop: downloader,  # type: ignore[arg-type]
    )
    return app, client, downloader


async def test_search_select_confirm_download_flow(tmp_path: Path) -> None:
    app, client, downloader = make_app(tmp_path)
    client.search_results = [ROOT, OTHER]

    async with app.run_test() as pilot:
        await pilot.press("enter")  # mode screen: "Search pages by title"
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)

        await pilot.press(*"root")
        await pilot.press("enter")  # submit query
        await app.workers.wait_for_complete()
        await pilot.pause()

        results = app.screen.query_one("#results", SelectionList)
        assert results.option_count == 2

        await pilot.press("space")  # tick highlighted first result (Root)
        assert results.selected == ["1"]

        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm")  # confirm with defaults: selected pages only
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert downloader.calls == [
            {
                "space_key": "DOC",
                "titles": ["Root"],
                "output_dir": tmp_path,
                "include_children": False,
                "force": False,
                "skip_unchanged": True,
                "combine_children": False,
                "download_html": False,
            }
        ]

        await pilot.press("escape")  # leave progress screen
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)
        assert results.selected == []


async def test_search_recursive_download_uses_include_children(tmp_path: Path) -> None:
    app, client, downloader = make_app(tmp_path)
    client.search_results = [ROOT]

    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press(*"root")
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.press("space", "d")
        await pilot.pause()

        await pilot.click("#children-recursive")  # fetches descendants for the count
        await app.workers.wait_for_complete()
        await pilot.pause()
        count_label = str(app.screen.query_one("#count").render())
        assert "3" in count_label  # Root + Child + Grandchild

        await pilot.click("#confirm")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert downloader.calls == [
            {
                "space_key": "DOC",
                "titles": ["Root"],
                "output_dir": tmp_path,
                "include_children": True,
                "force": False,
                "skip_unchanged": True,
                "combine_children": True,
                "download_html": False,
            }
        ]


async def test_browse_tree_subtree_select_and_download_flow(tmp_path: Path) -> None:
    app, client, downloader = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("down", "enter")  # mode screen: "Browse a space"
        await app.workers.wait_for_complete()  # space listing
        await pilot.pause()

        await pilot.press("tab", "tab")  # focus the space OptionList
        await pilot.press("enter")  # pick DOC
        await app.workers.wait_for_complete()  # root pages load
        await pilot.pause()

        tree = app.screen.query_one("#pages", Tree)
        assert len(tree.root.children) == 2

        await pilot.press("down")  # cursor onto "Root"
        await pilot.press("s")  # select subtree (fetches descendants)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert sorted(app.screen.selected) == ["1", "3", "4"]

        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert downloader.calls == [
            {
                "space_key": "DOC",
                "titles": ["Root", "Child", "Grandchild"],
                "output_dir": tmp_path,
                "include_children": False,
                "force": False,
                "skip_unchanged": True,
                "combine_children": False,
                "download_html": False,
            }
        ]


async def test_save_bulk_config_after_download(tmp_path: Path) -> None:
    app, client, downloader = make_app(tmp_path)
    client.search_results = [ROOT]
    bulk_path = tmp_path / "bulk.json"

    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press(*"root")
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("space", "d")
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        await pilot.press("s")  # save bulk config dialog
        await pilot.pause()
        path_input = app.screen.query_one("#save-path", Input)
        path_input.value = str(bulk_path)
        await pilot.press("enter")
        await pilot.pause()

        assert app.session_bulk_config == bulk_path

    config = json.loads(bulk_path.read_text(encoding="utf-8"))
    assert config["pages"] == [{"space": "DOC", "title": "Root", "include_children": False}]
    assert config["output_dir"] == str(tmp_path)


def _rendered_links(widget) -> set[tuple[str, str]]:
    links: set[tuple[str, str]] = set()
    for y in range(widget.size.height):
        for segment in widget.render_line(y):
            style = segment.style
            link = (getattr(style, "_link", None) or getattr(style, "link", None)) if style else None
            if link:
                links.add((segment.text, link))
    return links


async def test_search_results_link_titles_to_page_urls(tmp_path: Path) -> None:
    app, client, _ = make_app(tmp_path)
    client.search_results = [ROOT, OTHER]

    async with app.run_test() as pilot:
        await pilot.press("enter")  # mode screen: "Search pages by title"
        await pilot.pause()
        await pilot.press(*"root")
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

        links = _rendered_links(app.screen.query_one("#results", SelectionList))
        assert ("Root", ROOT.url) in links
        assert ("Other", OTHER.url) in links


async def test_browse_tree_links_titles_to_page_urls(tmp_path: Path) -> None:
    app, _, _ = make_app(tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("down", "enter")  # mode screen: "Browse a space"
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("tab", "tab")  # focus the space OptionList
        await pilot.press("enter")  # pick DOC
        await app.workers.wait_for_complete()
        await pilot.pause()

        links = _rendered_links(app.screen.query_one("#pages", Tree))
        assert ("Root", ROOT.url) in links
        assert ("Other", OTHER.url) in links
