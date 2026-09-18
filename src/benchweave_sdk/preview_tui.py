"""Textual lifecycle/status surface for the SDK preview server."""

from __future__ import annotations

from collections.abc import Callable

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Static


class PreviewStatusApp(App[None]):
    """Show preview readiness and own browser-open and shutdown actions."""

    TITLE = "BenchWeave SDK preview"
    BINDINGS = [("o", "open_browser", "Open browser"), ("q", "quit_preview", "Stop preview")]
    CSS = """
    Screen { align: center middle; }
    #status { width: 72; height: auto; padding: 2 4; border: round $accent; }
    #simulation { color: $warning; text-style: bold; margin-bottom: 1; }
    """

    def __init__(
        self,
        *,
        url: str,
        renderer_version: str,
        scenarios: int,
        open_browser: Callable[[str], bool],
        shutdown: Callable[[], None],
        open_on_mount: bool = False,
    ) -> None:
        super().__init__()
        self.url = url
        self.renderer_version = renderer_version
        self.scenarios = scenarios
        self._open_browser = open_browser
        self._shutdown_server = shutdown
        self._open_on_mount = open_on_mount
        self._shutdown_complete = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="status"):
            yield Static("SIMULATED PRESENTATION DATA", id="simulation")
            yield Static(f"Ready: {self.url}", id="url")
            yield Static(f"Preview API 1 · Renderer {self.renderer_version}")
            yield Static(f"{self.scenarios} scenarios available")
        yield Footer()

    def on_mount(self) -> None:
        if self._open_on_mount:
            self.action_open_browser()

    def action_open_browser(self) -> None:
        # ``webbrowser.open`` can block for seconds while a browser starts;
        # run it on a worker thread so the UI stays responsive.
        self.run_worker(self._open_browser_blocking, thread=True)

    def _open_browser_blocking(self) -> None:
        if not self._open_browser(self.url):
            self.call_from_thread(
                self.notify,
                f"Browser did not open; use {self.url}",
                severity="warning",
                timeout=10,
            )

    def _stop_server(self) -> None:
        if not self._shutdown_complete:
            self._shutdown_complete = True
            self._shutdown_server()

    def action_quit_preview(self) -> None:
        self._stop_server()
        self.exit()

    def on_unmount(self) -> None:
        self._stop_server()
