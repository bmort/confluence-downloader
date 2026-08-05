from __future__ import annotations

from dataclasses import dataclass, replace
from functools import partial

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, OptionList, Static, Tree
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from ..errors import ConfluencePdfError
from ..models import Page, Space
from .confirm import ConfirmScreen
from .plan import DownloadPlan
from .progress import ProgressScreen


class SpacePickerScreen(Screen):
    """Pick a space (and optionally a root page title) to browse."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self) -> None:
        super().__init__()
        self._spaces: list[Space] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Filter spaces… (enter uses the text as a space key)", id="space-filter")
        yield Input(placeholder="Root page title (optional — blank starts at the space roots)", id="root-title")
        yield OptionList(id="spaces")
        yield Static("Loading spaces…", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._load_spaces, thread=True, exclusive=True, group="spaces")

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _load_spaces(self) -> None:
        client = self.app.client  # type: ignore[attr-defined]
        try:
            spaces = client.list_spaces()
        except ConfluencePdfError as exc:
            self.app.call_from_thread(self._set_status, f"Could not list spaces: {exc}")
            return
        self.app.call_from_thread(self._show_spaces, spaces)

    def _show_spaces(self, spaces: list[Space]) -> None:
        self._spaces = spaces
        self._refresh_options()
        self._set_status(f"{len(spaces)} spaces — pick one, or type a key and press enter.")

    def _refresh_options(self) -> None:
        needle = self.query_one("#space-filter", Input).value.strip().lower()
        options = self.query_one("#spaces", OptionList)
        options.clear_options()
        for space in self._spaces:
            if needle and needle not in space.key.lower() and needle not in space.name.lower():
                continue
            # A Style object is required: Textual cannot parse Rich's "link <url>" string syntax.
            label = Text()
            label.append(space.key, style=Style(link=space.url) if space.url else None)
            if space.name:
                label.append(f"  {space.name}", style="dim")
            options.add_option(Option(label, id=space.key))
        if options.option_count:
            options.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "space-filter":
            self._refresh_options()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "space-filter":
            # Escape hatch for spaces the listing does not include (e.g. personal spaces).
            space_key = event.input.value.strip()
            if space_key:
                self._open_space(space_key)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self._open_space(event.option.id)

    def _open_space(self, space_key: str) -> None:
        root_title = self.query_one("#root-title", Input).value.strip()
        if not root_title:
            self.app.push_screen(TreeScreen(space_key))
            return
        self._set_status(f'Resolving "{root_title}" in {space_key}…')
        self.run_worker(
            lambda: self._resolve_root(space_key, root_title),
            thread=True,
            exclusive=True,
            group="resolve-root",
        )

    def _resolve_root(self, space_key: str, root_title: str) -> None:
        client = self.app.client  # type: ignore[attr-defined]
        try:
            root = client.resolve_page_by_title(space_key, root_title)
        except ConfluencePdfError as exc:
            self.app.call_from_thread(self._set_status, f"Could not resolve root page: {exc}")
            return
        self.app.call_from_thread(self.app.push_screen, TreeScreen(space_key, root_page=root))

    def action_back(self) -> None:
        self.app.pop_screen()


@dataclass
class _NodeData:
    page: Page
    loaded: bool = False
    loading: bool = False


class TreeScreen(Screen):
    """Lazy page tree for one space; tick pages or whole subtrees, then download."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("x", "toggle_page", "Select page"),
        Binding("s", "toggle_subtree", "Select subtree"),
        Binding("d", "download", "Download selected"),
    ]

    def __init__(self, space_key: str, root_page: Page | None = None) -> None:
        super().__init__()
        self.space_key = space_key
        self.root_page = root_page
        self.selected: dict[str, Page] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        if self.root_page:
            tree: Tree[_NodeData] = Tree(self._label(self.root_page), data=_NodeData(self.root_page), id="pages")
        else:
            tree = Tree(Text(f"Space {self.space_key}"), id="pages")
        yield tree
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        tree = self.query_one("#pages", Tree)
        tree.focus()
        if self.root_page is None:
            self._set_status(f"Loading root pages of {self.space_key}…")
            self.run_worker(partial(self._load_children, tree.root), thread=True)
        else:
            self._refresh_status()

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _refresh_status(self) -> None:
        count = len(self.selected)
        self._set_status(
            f"{count} page{'s' if count != 1 else ''} selected — "
            "x selects a page, s a subtree, d downloads."
        )

    def _label(self, page: Page) -> Text:
        tick = "☑" if page.id in self.selected else "☐"
        label = Text(f"{tick} ")
        # A Style object is required: Textual cannot parse Rich's "link <url>" string syntax.
        label.append(page.title, style=Style(link=page.url) if page.url else None)
        return label

    def _with_space(self, page: Page) -> Page:
        return page if page.space else replace(page, space=self.space_key)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        data = event.node.data
        if data is None or data.loaded or data.loading:
            return
        data.loading = True
        self.run_worker(partial(self._load_children, event.node), thread=True)

    def _load_children(self, node: TreeNode[_NodeData]) -> None:
        client = self.app.client  # type: ignore[attr-defined]
        if node.data is None:
            fetch = partial(client.list_space_root_pages, self.space_key)
        else:
            fetch = partial(client.list_child_pages, node.data.page.id)
        try:
            children = [self._with_space(page) for page in fetch()]
        except ConfluencePdfError as exc:
            self.app.call_from_thread(self._load_failed, node, str(exc))
            return
        self.app.call_from_thread(self._populate_children, node, children)

    def _load_failed(self, node: TreeNode[_NodeData], error: str) -> None:
        if node.data is not None:
            node.data.loading = False
        self._set_status(f"Could not load pages: {error}")

    def _populate_children(self, node: TreeNode[_NodeData], children: list[Page]) -> None:
        if node.data is not None:
            node.data.loaded = True
            node.data.loading = False
        for child in children:
            node.add(self._label(child), data=_NodeData(child))
        if not children:
            node.allow_expand = False
        node.expand()
        self._refresh_status()

    def _cursor_page_node(self) -> TreeNode[_NodeData] | None:
        node = self.query_one("#pages", Tree).cursor_node
        if node is None or node.data is None:
            self._set_status("Move the cursor onto a page first.")
            return None
        return node

    def action_toggle_page(self) -> None:
        node = self._cursor_page_node()
        if node is None:
            return
        page = node.data.page
        if page.id in self.selected:
            del self.selected[page.id]
        else:
            self.selected[page.id] = page
        node.set_label(self._label(page))
        self._refresh_status()

    def action_toggle_subtree(self) -> None:
        node = self._cursor_page_node()
        if node is None:
            return
        page = node.data.page
        deselect = page.id in self.selected
        self._set_status(f'{"Deselecting" if deselect else "Collecting"} subtree of "{page.title}"…')
        self.run_worker(
            partial(self._fetch_subtree, node, deselect),
            thread=True,
            exclusive=True,
            group="subtree",
        )

    def _fetch_subtree(self, node: TreeNode[_NodeData], deselect: bool) -> None:
        client = self.app.client  # type: ignore[attr-defined]
        page = node.data.page
        try:
            descendants = [self._with_space(child) for child in client.iter_descendants(page)]
        except ConfluencePdfError as exc:
            self.app.call_from_thread(self._set_status, f"Could not walk subtree: {exc}")
            return
        self.app.call_from_thread(self._apply_subtree, node, [page, *descendants], deselect)

    def _apply_subtree(self, node: TreeNode[_NodeData], pages: list[Page], deselect: bool) -> None:
        for page in pages:
            if deselect:
                self.selected.pop(page.id, None)
            else:
                self.selected[page.id] = page
        self._refresh_labels(node)
        self._refresh_status()

    def _refresh_labels(self, node: TreeNode[_NodeData]) -> None:
        if node.data is not None:
            node.set_label(self._label(node.data.page))
        for child in node.children:
            self._refresh_labels(child)

    def action_download(self) -> None:
        if not self.selected:
            self._set_status("No pages selected — use x or s to tick pages first.")
            return
        self.app.push_screen(
            ConfirmScreen(list(self.selected.values()), mode="tree", fallback_space=self.space_key),
            self._confirmed,
        )

    def _confirmed(self, plan: DownloadPlan | None) -> None:
        if plan is None:
            return
        self.app.push_screen(ProgressScreen(plan), self._after_download)

    def _after_download(self, _: None) -> None:
        self.selected.clear()
        self._refresh_labels(self.query_one("#pages", Tree).root)
        self._refresh_status()

    def action_back(self) -> None:
        self.app.pop_screen()
