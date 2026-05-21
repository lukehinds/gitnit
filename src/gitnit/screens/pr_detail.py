"""Pull request detail screen."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import LoadingIndicator, Static
from textual.worker import Worker, WorkerState

from gitnit.ai_reviewer import analyze_pr
from gitnit.cache import get_cached_pr_analysis
from gitnit.models import PRAnalysis, PRDetail
from gitnit.widgets.copyable_text import CopyableText

if TYPE_CHECKING:
    from gitnit.github_client import GitHubClient


class PRDetailScreen(Screen):
    """Detail screen for a single pull request with AI analysis."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("c", "copy_review", "Copy Review"),
        ("q", "quit_app", "Quit"),
    ]

    DEFAULT_CSS = """
    PRDetailScreen {
        background: $surface;
    }

    PRDetailScreen .detail-header {
        dock: top;
        height: 3;
        background: $primary-darken-2;
        padding: 0 2;
        layout: horizontal;
        align-vertical: middle;
    }

    PRDetailScreen .detail-body {
        padding: 1 2;
        height: 1fr;
        overflow-y: auto;
    }

    PRDetailScreen .analysis-panel {
        margin: 1 0;
        padding: 1 2;
        border: solid $primary-darken-1;
        background: $surface-darken-1;
        height: auto;
        min-height: 3;
    }

    PRDetailScreen .review-panel {
        margin: 1 0;
        padding: 1 2;
        border: solid $accent;
        background: $surface-darken-1;
        height: auto;
        min-height: 3;
    }

    PRDetailScreen .panel-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    PRDetailScreen .panel-content {
        color: $text;
        height: auto;
        min-height: 1;
    }

    PRDetailScreen .copy-hint {
        dock: bottom;
        height: 1;
        background: $surface-darken-2;
        color: $text-muted;
        text-align: center;
    }

    PRDetailScreen .loading-container {
        align: center middle;
        height: 1fr;
    }

    PRDetailScreen .risk-badge {
        text-style: bold;
        margin: 0 1;
    }

    PRDetailScreen .meta-row {
        layout: horizontal;
        height: auto;
        margin-bottom: 1;
    }

    PRDetailScreen .meta-label {
        width: 20;
        text-style: bold;
        color: $text-muted;
    }

    PRDetailScreen .meta-value {
        width: 1fr;
    }
    """

    def __init__(
        self,
        pr_number: int,
        github_client: GitHubClient,
        provider: str = "claude-code",
        model: str = "sonnet",
        prompt_version: str = "v1",
        repo: str = "",
        head_sha: str = "",
    ) -> None:
        super().__init__()
        self._pr_number = pr_number
        self._client = github_client
        self._provider = provider
        self._model = model
        self._prompt_version = prompt_version
        self._repo = repo
        self._head_sha = head_sha
        self._analysis: PRAnalysis | None = None
        self._pr_detail: PRDetail | None = None

    def compose(self) -> ComposeResult:
        with Container(classes="detail-header"):
            yield Static(f"PR #{self._pr_number}", classes="pr-title", id="pr-detail-title")
            yield Static("[dim]Loading...[/dim]", classes="pr-meta", id="pr-detail-meta")

        with Container(classes="loading-container", id="pr-detail-loading"):
            yield LoadingIndicator()
            yield Static("Fetching PR details and running AI analysis...")

        with VerticalScroll(classes="detail-body", id="pr-detail-body"):
            with Container(classes="analysis-panel", id="summary-panel"):
                yield Static("Summary", classes="panel-title")
                yield Static("Loading...", id="summary-content", classes="panel-content")

            with Container(classes="analysis-panel", id="risk-panel"):
                yield Static("Risk Assessment", classes="panel-title")
                yield Static("Loading...", id="risk-content", classes="panel-content")

            with Container(classes="review-panel", id="review-panel"):
                yield Static("Review Comment", classes="panel-title")
                yield CopyableText(id="review-comment")

        yield Static(
            " [bold]c[/bold] Copy review  [bold]Esc[/bold] Back  [bold]q[/bold] Quit ",
            classes="copy-hint",
        )

    def on_mount(self) -> None:
        body = self.query_one("#pr-detail-body")
        body.display = False
        self.run_worker(self._fetch_and_analyze(), name="pr_analysis", exclusive=True)

    async def _fetch_and_analyze(self) -> tuple[PRDetail, PRAnalysis]:
        from gitnit.ai_reviewer import _pr_analysis_from_dict

        # Check cache using known head_sha to avoid expensive GitHub + LLM calls
        head_sha = self._head_sha
        if not head_sha:
            head_sha = await asyncio.to_thread(self._client.get_pr_head_sha, self._pr_number)

        if self._repo and head_sha:
            cached = get_cached_pr_analysis(
                self._repo,
                self._pr_number,
                head_sha,
                provider=self._provider,
                model=self._model,
                prompt_version=self._prompt_version,
            )
            if cached:
                # Only fetch basic PR metadata, skip diff/files/comments
                detail = await asyncio.to_thread(
                    partial(self._client.get_pr_summary, self._pr_number, fetch_ci=False)
                )
                return detail, _pr_analysis_from_dict(cached)

        # No cache hit: full fetch + AI analysis
        detail = await asyncio.to_thread(self._client.get_pr_detail, self._pr_number)
        analysis = await analyze_pr(
            detail,
            provider=self._provider,
            model=self._model,
            repo=self._repo,
            prompt_version=self._prompt_version,
        )
        return detail, analysis

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name != "pr_analysis":
            return

        if event.state == WorkerState.SUCCESS and event.worker.result is not None:
            detail, analysis = event.worker.result
            self._pr_detail = detail
            self._analysis = analysis
            self._render_analysis()
        elif event.state == WorkerState.ERROR:
            try:
                loading = self.query_one("#pr-detail-loading")
                loading.display = False
                body = self.query_one("#pr-detail-body")
                body.display = True
                summary = self.query_one("#summary-content", Static)
                summary.update(f"[red]Error loading PR: {event.worker.error}[/red]")
            except Exception:
                pass

    def _render_analysis(self) -> None:
        if not self._pr_detail or not self._analysis:
            return

        try:
            loading = self.query_one("#pr-detail-loading")
            loading.display = False
            body = self.query_one("#pr-detail-body")
            body.display = True
        except Exception:
            return

        pr = self._pr_detail.pr
        analysis = self._analysis

        try:
            title = self.query_one("#pr-detail-title", Static)
            title.update(f"PR #{pr.number}: {pr.title}")
        except Exception:
            pass

        try:
            meta = self.query_one("#pr-detail-meta", Static)
            meta.update(
                f"[dim]{pr.author} | +{pr.additions}/-{pr.deletions} | "
                f"{pr.changed_files} files | {pr.size.value}[/dim]"
            )
        except Exception:
            pass

        try:
            summary = self.query_one("#summary-content", Static)
            summary_text = (
                f"{escape(analysis.summary)}\n\n"
                f"[bold]Security:[/bold] {escape(analysis.security_risks)}\n\n"
                f"[bold]Code Quality:[/bold] {escape(analysis.code_quality)}"
            )
            summary.update(summary_text)
            summary_panel = self.query_one("#summary-panel")
            summary_panel.refresh(layout=True)
        except Exception:
            pass

        risk_color = {
            "Low": "green",
            "Medium": "yellow",
            "High": "red",
            "Critical": "bold red",
        }.get(analysis.risk_level, "white")

        try:
            risk = self.query_one("#risk-content", Static)
            risk_text = (
                f"[bold]Risk Level:[/bold] [{risk_color}]"
                f"{escape(analysis.risk_level)}[/{risk_color}]\n\n"
                f"[bold]Disruption:[/bold] {escape(analysis.disruption_assessment)}\n\n"
                f"[bold]Backwards Compat:[/bold] {escape(analysis.backwards_compatibility)}\n\n"
                f"[bold]Semver Impact:[/bold] {escape(analysis.semver_impact)}"
            )
            risk.update(risk_text)
            risk_panel = self.query_one("#risk-panel")
            risk_panel.refresh(layout=True)
        except Exception:
            pass

        try:
            review = self.query_one("#review-comment", CopyableText)
            review.update_text(analysis.review_comment)
            review_panel = self.query_one("#review-panel")
            review_panel.refresh(layout=True)
        except Exception:
            pass

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_copy_review(self) -> None:
        if self._analysis and self._analysis.review_comment:
            try:
                review = self.query_one("#review-comment", CopyableText)
                review.copy_to_clipboard()
                self.notify("Review comment copied to clipboard")
            except Exception:
                self.notify("Failed to copy to clipboard", severity="error")
        else:
            self.notify("No review comment available yet", severity="warning")

    def action_quit_app(self) -> None:
        self.app.exit()
