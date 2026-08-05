from __future__ import annotations

from dataclasses import replace

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, RadioButton, RadioSet

from ..errors import ConfluencePdfError
from ..models import Page
from .plan import DownloadPlan

CHILDREN_NONE = "children-none"
CHILDREN_DIRECT = "children-direct"
CHILDREN_RECURSIVE = "children-recursive"


class ConfirmScreen(ModalScreen[DownloadPlan | None]):
    """Confirm a selection before downloading: children scope and toggles."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, pages: list[Page], *, mode: str, fallback_space: str | None = None) -> None:
        super().__init__()
        self.pages = pages
        self.mode = mode
        self.fallback_space = fallback_space
        self._children_mode = CHILDREN_NONE
        # Per-root child/descendant pages, fetched on demand for counts and expansion.
        self._direct_children: dict[str, list[Page]] | None = None
        self._descendants: dict[str, list[Page]] | None = None

    def compose(self) -> ComposeResult:
        count = len(self.pages)
        with Vertical(id="confirm-box"):
            yield Label(f"Download {count} selected page{'s' if count != 1 else ''}", id="confirm-title")
            if self.mode == "search":
                with RadioSet(id="children"):
                    yield RadioButton("Selected pages only", value=True, id=CHILDREN_NONE)
                    yield RadioButton("Include direct children", id=CHILDREN_DIRECT)
                    yield RadioButton("Include all descendants", id=CHILDREN_RECURSIVE)
                yield Checkbox(
                    "Combine each root and its children into one PDF",
                    value=True,
                    disabled=True,
                    id="combine",
                )
            yield Checkbox("Also download HTML copies", value=False, id="html")
            yield Checkbox("Also download attached files", value=False, id="attachments")
            yield Checkbox("Force re-download of unchanged pages", value=False, id="force")
            yield Label(self._count_text(count), id="count")
            with Horizontal(id="confirm-buttons"):
                yield Button("Download", variant="primary", id="confirm")
                yield Button("Cancel", id="cancel")

    @staticmethod
    def _count_text(count: int | None) -> str:
        if count is None:
            return "Pages to download: counting…"
        return f"Pages to download: {count}"

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        pressed_id = event.pressed.id or CHILDREN_NONE
        self._children_mode = pressed_id
        self.query_one("#combine", Checkbox).disabled = pressed_id != CHILDREN_RECURSIVE
        self._refresh_count()

    def _refresh_count(self) -> None:
        mode = self._children_mode
        if mode == CHILDREN_NONE:
            self._show_count(len(self.pages))
            return
        cache = self._direct_children if mode == CHILDREN_DIRECT else self._descendants
        if cache is not None:
            self._show_count(self._expanded_count(cache))
            return
        self._show_count(None)
        self.run_worker(
            lambda: self._fetch_children(mode),
            thread=True,
            exclusive=True,
            group="count",
        )

    def _show_count(self, count: int | None) -> None:
        self.query_one("#count", Label).update(self._count_text(count))
        self.query_one("#confirm", Button).disabled = count is None

    def _fetch_children(self, mode: str) -> None:
        client = self.app.client  # type: ignore[attr-defined]
        fetched: dict[str, list[Page]] = {}
        try:
            for page in self.pages:
                if mode == CHILDREN_DIRECT:
                    related = client.list_child_pages(page.id)
                else:
                    related = client.iter_descendants(page)
                # Child listings do not expand the space, so inherit the root's.
                fetched[page.id] = [
                    child if child.space else replace(child, space=page.space or self.fallback_space or "")
                    for child in related
                ]
        except ConfluencePdfError as exc:
            self.app.call_from_thread(self._fetch_failed, str(exc))
            return
        self.app.call_from_thread(self._store_children, mode, fetched)

    def _fetch_failed(self, error: str) -> None:
        self.query_one("#count", Label).update(f"Could not count pages: {error}")
        self.query_one("#confirm", Button).disabled = self._children_mode != CHILDREN_NONE

    def _store_children(self, mode: str, fetched: dict[str, list[Page]]) -> None:
        if mode == CHILDREN_DIRECT:
            self._direct_children = fetched
        else:
            self._descendants = fetched
        if mode == self._children_mode:
            self._show_count(self._expanded_count(fetched))

    def _expanded_count(self, children_by_root: dict[str, list[Page]]) -> int:
        return len({page.id for page in self._expanded_pages(children_by_root)})

    def _expanded_pages(self, children_by_root: dict[str, list[Page]]) -> list[Page]:
        pages: list[Page] = []
        seen: set[str] = set()
        for root in self.pages:
            for page in [root, *children_by_root.get(root.id, [])]:
                if page.id not in seen:
                    pages.append(page)
                    seen.add(page.id)
        return pages

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id == "confirm":
            self.dismiss(self._build_plan())

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _build_plan(self) -> DownloadPlan:
        html = self.query_one("#html", Checkbox).value
        attachments = self.query_one("#attachments", Checkbox).value
        force = self.query_one("#force", Checkbox).value
        if self.mode == "search" and self._children_mode == CHILDREN_RECURSIVE:
            return DownloadPlan(
                pages=self.pages,
                include_children=True,
                combine_children=self.query_one("#combine", Checkbox).value,
                download_html=html,
                download_attachments=attachments,
                force=force,
                fallback_space=self.fallback_space,
            )
        if self.mode == "search" and self._children_mode == CHILDREN_DIRECT:
            pages = self._expanded_pages(self._direct_children or {})
        else:
            pages = self.pages
        return DownloadPlan(
            pages=pages,
            download_html=html,
            download_attachments=attachments,
            force=force,
            fallback_space=self.fallback_space,
        )
