"""Pull request diff view screen."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import LoadingIndicator, Static
from textual.worker import Worker, WorkerState

from gitnit.models import PRDetail

if TYPE_CHECKING:
    from gitnit.github_client import GitHubClient


def _split_diff_by_file(diff: str) -> list[tuple[str, str]]:
    """Split concatenated diff into (filename, patch) pairs."""
    files: list[tuple[str, str]] = []
    current_file: str | None = None
    current_lines: list[str] = []

    for line in diff.splitlines():
        if line.startswith("--- "):
            if current_file is not None:
                files.append((current_file, "\n".join(current_lines)))
            current_file = line[4:]
            current_lines = []
        else:
            current_lines.append(line)

    if current_file is not None:
        files.append((current_file, "\n".join(current_lines)))

    return files


def _render_patch(patch: str) -> Text:
    """Render a file patch as a Rich Text object with color coding."""
    result = Text(no_wrap=False, end="")
    raw_lines = patch.splitlines()
    for i, line in enumerate(raw_lines):
        suffix = "\n" if i < len(raw_lines) - 1 else ""
        if line.startswith("@@"):
            result.append(line + suffix, style="dim yellow")
        elif line.startswith("+"):
            result.append(line + suffix, style="green")
        elif line.startswith("-"):
            result.append(line + suffix, style="red")
        else:
            result.append(line + suffix, style="dim")
    return result if result else Text("(no changes)", style="dim")


def _render_diff_text(diff: str) -> Text:
    """Render full diff as a Rich Text object (used after lazy-fetch)."""
    result = Text(no_wrap=False, end="")
    sep = "─" * 60
    first_file = True
    for line in diff.splitlines():
        if line.startswith("--- "):
            if not first_file:
                result.append("\n")
            first_file = False
            result.append(sep + "\n", style="bold dim")
            result.append(line[4:] + "\n", style="bold cyan")
            result.append(sep + "\n", style="bold dim")
        elif line.startswith("@@"):
            result.append(line + "\n", style="dim yellow")
        elif line.startswith("+"):
            result.append(line + "\n", style="green")
        elif line.startswith("-"):
            result.append(line + "\n", style="red")
        else:
            result.append(line + "\n", style="dim")
    return result


class PRDiffScreen(Screen):
    """Diff view for a pull request with AI review comment at the top."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("q", "confirm_quit", "Quit x2"),
    ]

    DEFAULT_CSS = """
    PRDiffScreen {
        background: $surface;
    }

    PRDiffScreen .diff-header {
        dock: top;
        height: 3;
        background: $primary-darken-2;
        padding: 0 2;
        layout: horizontal;
        align-vertical: middle;
    }

    PRDiffScreen .diff-body {
        padding: 1 2;
        height: 1fr;
    }

    PRDiffScreen .file-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    PRDiffScreen .diff-file-panel {
        margin: 1 0;
        padding: 1 2;
        border: solid $primary-darken-1;
        background: $surface-darken-1;
        height: auto;
        min-height: 3;
    }

    PRDiffScreen .diff-content {
        height: auto;
        min-height: 1;
    }

    PRDiffScreen .diff-loading {
        align: center middle;
        height: 5;
    }

    PRDiffScreen .hint-bar {
        dock: bottom;
        height: 1;
        background: $surface-darken-2;
        color: $text-muted;
        text-align: center;
    }

    PRDiffScreen .no-diff {
        color: $text-muted;
        text-align: center;
        margin: 2 0;
    }
    """

    def __init__(
        self,
        pr_detail: PRDetail,
        github_client: "GitHubClient | None" = None,
    ) -> None:
        super().__init__()
        self._pr_detail = pr_detail
        self._client = github_client

    def compose(self) -> ComposeResult:
        pr = self._pr_detail.pr
        with Container(classes="diff-header"):
            yield Static(f"PR #{pr.number}: {pr.title}", id="diff-title")
            yield Static(
                f"[dim]{pr.author} | +{pr.additions}/-{pr.deletions} | "
                f"{pr.changed_files} files | Diff View[/dim]",
                id="diff-meta",
            )

        with VerticalScroll(classes="diff-body", id="diff-scroll"):
            with Container(id="diff-area"):
                if self._pr_detail.diff:
                    file_diffs = _split_diff_by_file(self._pr_detail.diff)
                    if file_diffs:
                        for filename, patch in file_diffs:
                            with Container(classes="diff-file-panel"):
                                yield Static(filename, classes="file-title")
                                yield Static(_render_patch(patch), classes="diff-content")
                    else:
                        yield Static("[dim]No diff content.[/dim]", classes="no-diff")
                elif self._client:
                    with Container(classes="diff-loading"):
                        yield LoadingIndicator()
                        yield Static("Loading diff...")
                else:
                    yield Static("[dim]No diff available.[/dim]", classes="no-diff")

        yield Static(
            " [bold]Esc[/bold] Back  [bold]q q[/bold] Quit ",
            classes="hint-bar",
        )

    def on_mount(self) -> None:
        self.query_one("#diff-scroll", VerticalScroll).focus()
        if not self._pr_detail.diff and self._client:
            self.run_worker(
                self._fetch_diff(), name="fetch_diff", exclusive=True
            )

    async def _fetch_diff(self) -> PRDetail:
        assert self._client is not None
        return await asyncio.to_thread(
            self._client.get_pr_detail, self._pr_detail.pr.number
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name != "fetch_diff":
            return

        if event.state == WorkerState.SUCCESS and event.worker.result is not None:
            detail: PRDetail = event.worker.result
            self._pr_detail = detail
            self._replace_diff_area(detail.diff)
        elif event.state == WorkerState.ERROR:
            self._replace_diff_area(None, error=str(event.worker.error))

    def _replace_diff_area(self, diff: str | None, error: str | None = None) -> None:
        try:
            area = self.query_one("#diff-area")
            area.remove_children()
            if error:
                err_text = Text(no_wrap=False, end="")
                err_text.append(f"Failed to load diff: {error}", style="red")
                area.mount(Static(err_text, classes="no-diff"))
            elif not diff:
                area.mount(Static("No diff available.", classes="no-diff"))
            else:
                area.mount(
                    Static(
                        _render_diff_text(diff),
                        id="diff-content-static",
                        classes="diff-content",
                    )
                )
        except Exception:
            pass

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_confirm_quit(self) -> None:
        self.app.action_confirm_quit()
