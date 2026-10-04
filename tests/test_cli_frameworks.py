"""SDK CLI framework boundaries remain stable and automation-safe."""

from io import StringIO
from pathlib import Path

from click.testing import CliRunner


def test_sdk_exposes_click_command_group() -> None:
    from benchweave_sdk.cli import cli

    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for command in ("new", "check", "inventory", "check-ui", "check-preset", "preview-ui"):
        assert command in result.output


def test_click_usage_and_domain_exit_codes(tmp_path: Path) -> None:
    from benchweave_sdk.cli import cli

    runner = CliRunner()
    assert runner.invoke(cli, ["check-ui"]).exit_code == 2
    result = runner.invoke(cli, ["check", str(tmp_path / "missing.json")])
    assert result.exit_code == 1


def test_findings_render_author_strings_literally() -> None:
    from benchweave_sdk.console import ConsoleOutput

    stream = StringIO()
    output = ConsoleOutput(file=stream, terminal=True)
    output.findings([("[red]evil[/red]", "presentation.json", "[bold]spoofed[/bold]")])
    rendered = stream.getvalue()
    assert "[red]evil[/red]" in rendered
    assert "[bold]spoofed[/bold]" in rendered


def test_findings_rows_stay_single_line_in_non_terminal_mode() -> None:
    """S13: non-terminal findings are prefix-shaped machine output — a row
    must survive rich's default width 80 as ONE greppable line, the same
    corruption class document() shed."""
    from benchweave_sdk.console import ConsoleOutput

    stream = StringIO()
    output = ConsoleOutput(file=stream, terminal=False)
    long_path = "packages/" + ("very-long-" * 12) + "plugin-directory/panel/index.json"
    output.findings([("panel_unavailable", long_path, "")])
    rendered = stream.getvalue()
    finding_lines = [line for line in rendered.splitlines() if line.startswith("panel_unavailable")]
    assert len(finding_lines) == 1, rendered
    assert long_path in rendered, rendered


def test_textual_preview_status_lifecycle() -> None:
    from benchweave_sdk.preview_tui import PreviewStatusApp

    shutdown: list[bool] = []
    opened: list[str] = []

    def record_open(url: str) -> bool:
        opened.append(url)
        return True

    app = PreviewStatusApp(
        url="http://127.0.0.1:49152",
        renderer_version="0.1.0",
        scenarios=11,
        open_browser=record_open,
        shutdown=lambda: shutdown.append(True),
    )

    async def exercise() -> None:
        async with app.run_test() as pilot:
            assert "SIMULATED PRESENTATION DATA" in str(app.query_one("#simulation").render())
            await pilot.press("o")
            assert opened == ["http://127.0.0.1:49152"]
            await pilot.press("q")
        assert shutdown == [True]

    import asyncio

    asyncio.run(exercise())
