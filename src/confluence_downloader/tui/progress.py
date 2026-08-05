from __future__ import annotations

import threading
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Static

from ..config import update_bulk_config
from ..errors import ConfluencePdfError
from ..utils import decorate_log, strip_hyperlinks
from .plan import DownloadPlan, PlanResult, execute_plan

DEFAULT_BULK_CONFIG = Path("bulk-config.json")


class ProgressScreen(Screen[None]):
    """Streams downloader log lines while a plan runs, then shows the summary."""

    BINDINGS = [
        Binding("c", "cancel", "Cancel"),
        Binding("s", "save_bulk", "Save bulk config"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, plan: DownloadPlan) -> None:
        super().__init__()
        self.plan = plan
        self._stop = threading.Event()
        self._done = False
        self._result: PlanResult | None = None

    def compose(self) -> ComposeResult:
        count = len(self.plan.pages)
        yield Header()
        yield Static(
            f"Downloading {count} page{'s' if count != 1 else ''}"
            f"{' (with descendants)' if self.plan.include_children else ''}"
            f" to {self.app.output_dir}",  # type: ignore[attr-defined]
            id="progress-title",
        )
        yield RichLog(id="progress-log", wrap=True, markup=False)
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._set_status("Downloading… press c to cancel after the current page.")
        self.run_worker(self._run, thread=True, exclusive=True, group="download")

    def _run(self) -> None:
        def logger(level: str, message: str) -> None:
            self.app.call_from_thread(self._write_log, level, message)

        downloader = self.app.downloader_factory(  # type: ignore[attr-defined]
            self.app.client,  # type: ignore[attr-defined]
            logger,
            self._stop.is_set,
        )
        result = execute_plan(
            self.plan,
            downloader,
            output_dir=self.app.output_dir,  # type: ignore[attr-defined]
            should_stop=self._stop.is_set,
            log=logger,
        )
        self.app.call_from_thread(self._finish, result)

    def _write_log(self, level: str, message: str) -> None:
        if level != "normal":
            return
        self.query_one("#progress-log", RichLog).write(decorate_log(strip_hyperlinks(message)))

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _finish(self, result: PlanResult) -> None:
        self._done = True
        self._result = result
        log = self.query_one("#progress-log", RichLog)
        log.write("")
        cancelled = result.cancelled or self._stop.is_set()
        log.write(f"{'🛑 Cancelled' if cancelled else '📊 Finished'}:")
        log.write(f"  Exported: {result.exported}")
        log.write(f"  Skipped existing: {result.skipped}")
        log.write(f"  Skipped unchanged: {result.skipped_unchanged}")
        log.write(f"  Failed: {result.failed}")
        for summary in result.summaries:
            for failure in summary.failures:
                log.write(f"  ❌ {failure.page.title}: {failure.error}")
        for error in result.errors:
            log.write(f"  ❌ {error}")
        if result.manifest_path:
            log.write(f"  Manifest: {result.manifest_path}")
        self._set_status("Done — escape returns, s saves the selection to a bulk config.")

    def action_cancel(self) -> None:
        if self._done:
            return
        self._stop.set()
        self._set_status("Cancelling after the current page…")

    def action_back(self) -> None:
        if not self._done:
            self._set_status("Still downloading — press c to cancel first.")
            return
        self.dismiss(None)

    def action_save_bulk(self) -> None:
        if not self._done:
            self._set_status("Still downloading — wait for it to finish before saving.")
            return
        default = self.app.session_bulk_config or DEFAULT_BULK_CONFIG  # type: ignore[attr-defined]
        self.app.push_screen(SaveBulkConfigScreen(default), self._save_bulk_config)

    def _save_bulk_config(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            update_bulk_config(
                path,
                self.plan.bulk_requests(),
                output_dir=self.app.output_dir,  # type: ignore[attr-defined]
            )
        except (ConfluencePdfError, OSError) as exc:
            self._set_status(f"Could not save bulk config: {exc}")
            return
        self.app.session_bulk_config = path  # type: ignore[attr-defined]
        self.query_one("#progress-log", RichLog).write(f"📋 Bulk config updated: {path}")
        self._set_status("Bulk config saved — escape returns.")


class SaveBulkConfigScreen(ModalScreen[Path | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, default: Path) -> None:
        super().__init__()
        self.default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="save-box"):
            yield Label("Save selection to bulk config", id="save-title")
            yield Input(value=str(self.default), id="save-path")
            with Horizontal(id="save-buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._submit()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        value = self.query_one("#save-path", Input).value.strip()
        if not value:
            return
        self.dismiss(Path(value))
