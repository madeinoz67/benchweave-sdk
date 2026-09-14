"""Rich-backed SDK output with stable plain text for automation."""

from __future__ import annotations

import sys
from typing import TextIO

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


class ConsoleOutput:
    """Render restrained terminal output without changing semantic messages."""

    def __init__(self, *, file: TextIO | None = None, terminal: bool | None = None) -> None:
        target = file or sys.stdout
        self.terminal = target.isatty() if terminal is None else terminal
        self.console = Console(
            file=target,
            force_terminal=self.terminal,
            no_color=not self.terminal,
        )

    def message(self, text: str, *, style: str | None = None) -> None:
        self.console.print(text, style=style if self.terminal else None, markup=False)

    def document(self, value: object) -> None:
        import json

        self.message(json.dumps(value, indent=2))

    def findings(self, rows: list[tuple[str, str, str]]) -> None:
        if not self.terminal:
            for code, path, message in rows:
                self.message(f"{code}: {path}: {message}")
            return
        table = Table(title="Presentation findings", box=None)
        table.add_column("Code", style="yellow")
        table.add_column("Path")
        table.add_column("Message")
        for row in rows:
            table.add_row(*row)
        self.console.print(table)

    def preview_ready(self, url: str, *, scenarios: int, renderer_version: str) -> None:
        text = (
            f"SIMULATED PRESENTATION DATA: {url}\n"
            f"Renderer {renderer_version} · {scenarios} scenarios"
        )
        if self.terminal:
            self.console.print(Panel(text, title="BenchWeave SDK preview", border_style="cyan"))
        else:
            self.message(text)
