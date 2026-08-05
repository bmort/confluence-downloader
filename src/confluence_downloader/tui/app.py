from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from ..client import ConfluenceClient
from ..downloader import LogFn, PdfDownloader
from .browse import SpacePickerScreen
from .search import SearchScreen

DownloaderFactory = Callable[[ConfluenceClient, LogFn, Callable[[], bool]], PdfDownloader]


def _default_downloader_factory(
    client: ConfluenceClient,
    logger: LogFn,
    should_stop: Callable[[], bool],
) -> PdfDownloader:
    return PdfDownloader(client, logger=logger, should_stop=should_stop)


class ModeScreen(Screen):
    BINDINGS = [Binding("escape", "app.quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("What do you want to do?", id="mode-title")
        yield OptionList(
            Option("Search pages by title", id="search"),
            Option("Browse a space", id="browse"),
            id="modes",
        )
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == "search":
            self.app.push_screen(SearchScreen())
        elif event.option.id == "browse":
            self.app.push_screen(SpacePickerScreen())


class ConfluenceTui(App):
    """Interactive search, browse, and download for Confluence pages."""

    TITLE = "Confluence Downloader"
    BINDINGS = [Binding("q", "quit", "Quit")]
    CSS = """
    #mode-title, #progress-title {
        padding: 1 2;
        text-style: bold;
    }
    #modes {
        margin: 0 2;
        width: 50;
    }
    #status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #search-bar {
        height: 3;
    }
    #query {
        width: 1fr;
    }
    #space {
        width: 24;
    }
    #limit {
        width: 12;
    }
    #progress-log {
        margin: 0 1;
    }
    ConfirmScreen, SaveBulkConfigScreen {
        align: center middle;
    }
    #confirm-box, #save-box {
        width: 70;
        height: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #confirm-title, #save-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #count {
        margin-top: 1;
    }
    #confirm-buttons, #save-buttons {
        height: auto;
        margin-top: 1;
        align-horizontal: right;
    }
    #confirm-buttons Button, #save-buttons Button {
        margin-left: 2;
    }
    """

    def __init__(
        self,
        *,
        client: ConfluenceClient,
        output_dir: Path = Path("."),
        downloader_factory: DownloaderFactory | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.output_dir = output_dir
        self.downloader_factory = downloader_factory or _default_downloader_factory
        # Remembered for the session so repeated saves do not re-ask.
        self.session_bulk_config: Path | None = None

    def on_mount(self) -> None:
        self.push_screen(ModeScreen())
