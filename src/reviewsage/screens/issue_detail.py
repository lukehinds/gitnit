"""Issue detail screen."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import LoadingIndicator, Static
from textual.worker import Worker, WorkerState

from reviewsage.ai_reviewer import analyze_issue
from reviewsage.cache import get_cached_issue_analysis
from reviewsage.models import IssueAnalysis, IssueDetail
from reviewsage.widgets.copyable_text import CopyableText

if TYPE_CHECKING:
    from reviewsage.github_client import GitHubClient


class IssueDetailScreen(Screen):
    """Detail screen for a single issue with AI analysis."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("c", "copy_fix", "Copy Fix"),
        ("q", "quit_app", "Quit"),
    ]

    DEFAULT_CSS = """
    IssueDetailScreen {
        background: $surface;
    }

    IssueDetailScreen .detail-header {
        dock: top;
        height: 3;
        background: $primary-darken-2;
        padding: 0 2;
        layout: horizontal;
        align-vertical: middle;
    }

    IssueDetailScreen .detail-body {
        padding: 1 2;
        height: 1fr;
        overflow-y: auto;
    }

    IssueDetailScreen .analysis-panel {
        margin: 1 0;
        padding: 1 2;
        border: solid $primary-darken-1;
        background: $surface-darken-1;
        height: auto;
        min-height: 3;
    }

    IssueDetailScreen .review-panel {
        margin: 1 0;
        padding: 1 2;
        border: solid $accent;
        background: $surface-darken-1;
        height: auto;
        min-height: 3;
    }

    IssueDetailScreen .panel-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    IssueDetailScreen .panel-content {
        color: $text;
        height: auto;
        min-height: 1;
    }

    IssueDetailScreen .copy-hint {
        dock: bottom;
        height: 1;
        background: $surface-darken-2;
        color: $text-muted;
        text-align: center;
    }

    IssueDetailScreen .loading-container {
        align: center middle;
        height: 1fr;
    }
    """

    def __init__(
        self,
        issue_number: int,
        github_client: GitHubClient,
        model: str = "sonnet",
        repo: str = "",
    ) -> None:
        super().__init__()
        self._issue_number = issue_number
        self._client = github_client
        self._model = model
        self._repo = repo
        self._analysis: IssueAnalysis | None = None
        self._issue_detail: IssueDetail | None = None

    def compose(self) -> ComposeResult:
        with Container(classes="detail-header"):
            yield Static(
                f"Issue #{self._issue_number}", classes="pr-title", id="issue-detail-title"
            )
            yield Static("[dim]Loading...[/dim]", classes="pr-meta", id="issue-detail-meta")

        with Container(classes="loading-container", id="issue-detail-loading"):
            yield LoadingIndicator()
            yield Static("Fetching issue details and running AI analysis...")

        with VerticalScroll(classes="detail-body", id="issue-detail-body"):
            with Container(classes="analysis-panel", id="issue-analysis-panel"):
                yield Static("Issue Analysis", classes="panel-title")
                yield Static("Loading...", id="issue-analysis-content", classes="panel-content")

            with Container(classes="review-panel", id="issue-fix-panel"):
                yield Static("Suggested Fix", classes="panel-title")
                yield CopyableText(id="fix-suggestion")

        yield Static(
            " [bold]c[/bold] Copy fix  [bold]Esc[/bold] Back  [bold]q[/bold] Quit ",
            classes="copy-hint",
        )

    def on_mount(self) -> None:
        body = self.query_one("#issue-detail-body")
        body.display = False
        self.run_worker(self._fetch_and_analyze(), name="issue_analysis", exclusive=True)

    async def _fetch_and_analyze(self) -> tuple[IssueDetail, IssueAnalysis]:
        from reviewsage.ai_reviewer import _issue_analysis_from_dict

        # Check cache before expensive GitHub + LLM calls
        if self._repo:
            cached = get_cached_issue_analysis(self._repo, self._issue_number)
            if cached:
                detail = self._client.get_issue_summary(self._issue_number)
                return detail, _issue_analysis_from_dict(cached)

        # No cache hit: full fetch + AI analysis
        detail = self._client.get_issue_detail(self._issue_number)
        analysis = await analyze_issue(detail, model=self._model, repo=self._repo)
        return detail, analysis

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name != "issue_analysis":
            return

        if event.state == WorkerState.SUCCESS and event.worker.result is not None:
            detail, analysis = event.worker.result
            self._issue_detail = detail
            self._analysis = analysis
            self._render_analysis()
        elif event.state == WorkerState.ERROR:
            try:
                loading = self.query_one("#issue-detail-loading")
                loading.display = False
                body = self.query_one("#issue-detail-body")
                body.display = True
                content = self.query_one("#issue-analysis-content", Static)
                content.update(f"[red]Error loading issue: {event.worker.error}[/red]")
            except Exception:
                pass

    def _render_analysis(self) -> None:
        if not self._issue_detail or not self._analysis:
            return

        try:
            loading = self.query_one("#issue-detail-loading")
            loading.display = False
            body = self.query_one("#issue-detail-body")
            body.display = True
        except Exception:
            return

        issue = self._issue_detail.issue
        analysis = self._analysis

        try:
            title = self.query_one("#issue-detail-title", Static)
            title.update(f"Issue #{issue.number}: {issue.title}")
        except Exception:
            pass

        try:
            meta = self.query_one("#issue-detail-meta", Static)
            label_text = issue.label_raw if issue.label_raw else "no label"
            meta_str = f"[dim]{issue.author} | {label_text} | {issue.comment_count} comments[/dim]"
            meta.update(meta_str)
        except Exception:
            pass

        severity_color = {
            "Critical": "bold red",
            "High": "red",
            "Medium": "yellow",
            "Low": "green",
            "Info": "blue",
        }.get(analysis.severity.value, "white")

        try:
            content = self.query_one("#issue-analysis-content", Static)
            analysis_text = (
                f"[bold]Severity:[/bold] [{severity_color}]"
                f"{escape(analysis.severity.value)}[/{severity_color}]\n\n"
                f"[bold]Overview:[/bold]\n{escape(analysis.overview)}\n\n"
                f"[bold]Suspected Cause:[/bold]\n{escape(analysis.suspected_cause)}"
            )
            content.update(analysis_text)
            analysis_panel = self.query_one("#issue-analysis-panel")
            analysis_panel.refresh(layout=True)
        except Exception:
            pass

        try:
            fix = self.query_one("#fix-suggestion", CopyableText)
            fix.update_text(analysis.suggested_fix)
            fix_panel = self.query_one("#issue-fix-panel")
            fix_panel.refresh(layout=True)
        except Exception:
            pass

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_copy_fix(self) -> None:
        if self._analysis and self._analysis.suggested_fix:
            try:
                fix = self.query_one("#fix-suggestion", CopyableText)
                fix.copy_to_clipboard()
                self.notify("Fix suggestion copied to clipboard")
            except Exception:
                self.notify("Failed to copy to clipboard", severity="error")
        else:
            self.notify("No fix suggestion available yet", severity="warning")

    def action_quit_app(self) -> None:
        self.app.exit()
