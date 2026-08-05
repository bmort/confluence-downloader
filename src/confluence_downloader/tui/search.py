from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, SelectionList, Static
from textual.widgets.selection_list import Selection

from ..errors import ConfluencePdfError
from ..models import Page
from ..utils import format_last_edited_age
from .confirm import ConfirmScreen
from .plan import DownloadPlan
from .progress import ProgressScreen

MAX_SEARCH_LIMIT = 100
DEFAULT_SEARCH_LIMIT = 25


class SearchScreen(Screen):
    """Title search with a multi-select result list."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("d", "download", "Download selected"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._pages: dict[str, Page] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="search-bar"):
            yield Input(placeholder="Search page titles…", id="query")
            yield Input(placeholder="Space (optional)", id="space")
            yield Input(
                value=str(DEFAULT_SEARCH_LIMIT),
                placeholder="Limit",
                type="integer",
                id="limit",
            )
        yield SelectionList(id="results")
        yield Static("Type a query and press enter to search.", id="status")
        yield Footer()

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._start_search()

    def _start_search(self) -> None:
        query = self.query_one("#query", Input).value.strip()
        if not query:
            self._set_status("Enter a search query first.")
            return
        space = self.query_one("#space", Input).value.strip() or None
        limit = self._resolved_limit()
        self._set_status(f'Searching for "{query}"…')
        self.run_worker(
            lambda: self._search(query, space, limit),
            thread=True,
            exclusive=True,
            group="search",
        )

    def _resolved_limit(self) -> int:
        raw = self.query_one("#limit", Input).value.strip()
        try:
            limit = int(raw)
        except ValueError:
            limit = DEFAULT_SEARCH_LIMIT
        return max(1, min(MAX_SEARCH_LIMIT, limit))

    def _search(self, query: str, space: str | None, limit: int) -> None:
        client = self.app.client  # type: ignore[attr-defined]
        try:
            pages = client.search_pages_by_title(query, space_key=space, limit=limit)
        except ConfluencePdfError as exc:
            self.app.call_from_thread(self._set_status, f"Search failed: {exc}")
            return
        self.app.call_from_thread(self._show_results, pages)

    def _show_results(self, pages: list[Page]) -> None:
        results = self.query_one("#results", SelectionList)
        results.clear_options()
        self._pages = {page.id: page for page in pages}
        for page in pages:
            label = Text()
            # A Style object is required: Textual cannot parse Rich's "link <url>" string syntax.
            label.append(page.title, style=Style(link=page.url) if page.url else None)
            details = "  ".join(part for part in (page.space, format_last_edited_age(page.version_when)) if part)
            if details:
                label.append(f"  {details}", style="dim")
            results.add_option(Selection(label, page.id))
        if pages:
            self._set_status(f"{len(pages)} matches — space toggles a page, d downloads the selection.")
            results.highlighted = 0
            results.focus()
        else:
            self._set_status("No matching pages found.")

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_download(self) -> None:
        results = self.query_one("#results", SelectionList)
        selected = [self._pages[page_id] for page_id in results.selected]
        if not selected:
            self._set_status("No pages selected — use space to tick results first.")
            return
        self.app.push_screen(ConfirmScreen(selected, mode="search"), self._confirmed)

    def _confirmed(self, plan: DownloadPlan | None) -> None:
        if plan is None:
            return
        self.app.push_screen(ProgressScreen(plan), self._after_download)

    def _after_download(self, _: None) -> None:
        self.query_one("#results", SelectionList).deselect_all()
        self._set_status("Selection cleared — search again or pick more pages.")
