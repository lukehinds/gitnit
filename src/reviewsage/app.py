"""Main ReviewSage Textual application."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, LoadingIndicator, Static, TabbedContent, TabPane

from reviewsage.github_client import GitHubClient
from reviewsage.screens.issue_detail import IssueDetailScreen
from reviewsage.screens.issue_list import IssueListView
from reviewsage.screens.pr_detail import PRDetailScreen
from reviewsage.screens.pr_list import PRListView

POLL_INTERVAL_SECONDS = 60


class NotificationScreen(ModalScreen):
    """Modal popup announcing new PRs or issues."""

    BINDINGS = [
        ("enter", "dismiss", "OK"),
        ("escape", "dismiss", "OK"),
    ]

    DEFAULT_CSS = """
    NotificationScreen {
        align: center middle;
    }

    NotificationScreen > .notify-panel {
        width: 56;
        height: auto;
        background: $surface;
        border: thick $accent;
        padding: 2 3;
    }

    NotificationScreen > .notify-panel .notify-title {
        text-style: bold;
        text-align: center;
        color: $accent;
        margin-bottom: 1;
    }

    NotificationScreen > .notify-panel .notify-body {
        text-align: center;
        margin-bottom: 1;
    }

    NotificationScreen > .notify-panel .notify-hint {
        text-align: center;
        color: $text-muted;
    }
    """

    def __init__(self, messages: list[str]) -> None:
        super().__init__()
        self._messages = messages

    def compose(self) -> ComposeResult:
        with Container(classes="notify-panel"):
            yield Static("New Activity", classes="notify-title")
            for msg in self._messages:
                yield Static(msg, classes="notify-body")
            yield Static("[dim]Press Enter to close[/dim]", classes="notify-hint")

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class HelpScreen(ModalScreen):
    """Help overlay showing keybindings."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("question_mark", "dismiss", "Close"),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }

    HelpScreen > .help-panel {
        width: 64;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 2 3;
    }

    HelpScreen > .help-panel .help-title {
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
        color: $accent;
    }

    HelpScreen > .help-panel .help-row {
        layout: horizontal;
        height: auto;
        margin-bottom: 0;
    }

    HelpScreen > .help-panel .help-key {
        width: 18;
        text-style: bold;
        color: $accent;
    }

    HelpScreen > .help-panel .help-desc {
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(classes="help-panel"):
            yield Static("ReviewSage - Keyboard Shortcuts", classes="help-title")
            yield Static("")

            for key, desc in [
                ("Up/Down", "Navigate list items"),
                ("Enter", "Open selected item"),
                ("Escape", "Go back / Close"),
                ("Tab", "Switch between tabs"),
                ("s", "Toggle issue sort order"),
                ("c", "Copy review/fix to clipboard"),
                ("r", "Refresh current view"),
                ("?", "Show this help"),
                ("q", "Quit application"),
            ]:
                with Container(classes="help-row"):
                    yield Static(f"  {key}", classes="help-key")
                    yield Static(desc, classes="help-desc")

            yield Static("")
            yield Static("[dim]Press Esc or ? to close[/dim]", id="help-close-hint")

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class ReviewSageApp(App):
    """ReviewSage - AI-powered PR and issue review TUI."""

    TITLE = "ReviewSage"
    SUB_TITLE = ""
    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("question_mark", "show_help", "Help", show=True, key_display="?"),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("s", "toggle_sort", "Sort", show=True),
    ]

    def __init__(self, repo: str, model: str = "sonnet") -> None:
        super().__init__()
        self._repo = repo
        self._model = model
        self._client: GitHubClient | None = None
        self._known_pr_count: int = -1
        self._known_issue_count: int = -1
        self._poll_timer = None

    DEFAULT_CSS = """
    .init-loading {
        align: center middle;
        height: 1fr;
    }

    .init-loading LoadingIndicator {
        color: $accent;
    }

    .init-loading .init-text {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }

    .init-loading .init-repo {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(classes="init-loading", id="init-loading"):
            yield Static(f"Connecting to {self._repo}", classes="init-repo")
            yield LoadingIndicator()
            yield Static("Fetching repository data...", classes="init-text")
        with TabbedContent("Pull Requests", "Issues", id="main-tabs"):
            with TabPane("Pull Requests", id="tab-prs"):
                yield Static("", id="pr-init-msg")
            with TabPane("Issues", id="tab-issues"):
                yield Static("", id="issue-init-msg")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self._repo
        self.query_one("#main-tabs", TabbedContent).display = False
        self.run_worker(self._initialize(), name="init", exclusive=True)

    async def _initialize(self) -> GitHubClient:
        return GitHubClient(self._repo)

    def on_worker_state_changed(self, event) -> None:
        from textual.worker import WorkerState

        if event.worker.name == "init":
            if event.state == WorkerState.SUCCESS and event.worker.result is not None:
                self._client = event.worker.result
                self._hide_init_loading()
                self._setup_views()
            elif event.state == WorkerState.ERROR:
                try:
                    loading = self.query_one("#init-loading")
                    loading.query_one(LoadingIndicator).display = False
                    loading.query_one(".init-text", Static).update(
                        f"[red]Failed to connect: {event.worker.error}[/red]"
                    )
                except Exception:
                    pass
        elif (
            event.worker.name in ("initial_counts", "poll_counts")
            and event.state == WorkerState.SUCCESS
            and event.worker.result is not None
        ):
            pr_count, issue_count = event.worker.result
            self._handle_poll_result(pr_count, issue_count)

    def _hide_init_loading(self) -> None:
        try:
            self.query_one("#init-loading").display = False
            self.query_one("#main-tabs", TabbedContent).display = True
        except Exception:
            pass

    def _setup_views(self) -> None:
        if not self._client:
            return

        try:
            pr_tab = self.query_one("#tab-prs", TabPane)
            pr_msg = self.query_one("#pr-init-msg", Static)
            pr_msg.remove()
            pr_view = PRListView(self._client, repo=self._repo, id="pr-list-view")
            pr_tab.mount(pr_view)
        except Exception:
            pass

        try:
            issue_tab = self.query_one("#tab-issues", TabPane)
            issue_msg = self.query_one("#issue-init-msg", Static)
            issue_msg.remove()
            issue_view = IssueListView(self._client, repo=self._repo, id="issue-list-view")
            issue_tab.mount(issue_view)
        except Exception:
            pass

        self._start_polling()

    def _start_polling(self) -> None:
        """Begin periodic polling for new PRs and issues."""
        if not self._client:
            return
        self.run_worker(self._fetch_counts(), name="initial_counts", exclusive=False)
        self._poll_timer = self.set_interval(
            POLL_INTERVAL_SECONDS, self._poll_for_updates, pause=False
        )

    async def _fetch_counts(self) -> tuple[int, int]:
        """Fetch current PR and issue counts."""
        pr_count = self._client.get_open_pr_count() if self._client else -1
        issue_count = self._client.get_open_issue_count() if self._client else -1
        return pr_count, issue_count

    def _poll_for_updates(self) -> None:
        """Timer callback: start a worker to check counts."""
        if self._client:
            self.run_worker(self._fetch_counts(), name="poll_counts", exclusive=False)

    def _handle_poll_result(self, pr_count: int, issue_count: int) -> None:
        """Compare new counts against known counts and show notification if changed."""
        if pr_count < 0 or issue_count < 0:
            return

        if self._known_pr_count < 0 or self._known_issue_count < 0:
            self._known_pr_count = pr_count
            self._known_issue_count = issue_count
            return

        messages: list[str] = []
        new_prs = pr_count - self._known_pr_count
        new_issues = issue_count - self._known_issue_count

        if new_prs > 0:
            label = "pull request" if new_prs == 1 else "pull requests"
            messages.append(f"[bold]{new_prs}[/bold] new {label}")
        if new_issues > 0:
            label = "issue" if new_issues == 1 else "issues"
            messages.append(f"[bold]{new_issues}[/bold] new {label}")

        self._known_pr_count = pr_count
        self._known_issue_count = issue_count

        if messages:
            self.push_screen(NotificationScreen(messages))

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_toggle_sort(self) -> None:
        try:
            issue_view = self.query_one("#issue-list-view", IssueListView)
            issue_view.toggle_sort()
        except Exception:
            pass

    def action_refresh(self) -> None:
        try:
            pr_view = self.query_one("#pr-list-view", PRListView)
            pr_view._load_page(pr_view._current_page)
        except Exception:
            pass
        try:
            issue_view = self.query_one("#issue-list-view", IssueListView)
            issue_view._load_page(issue_view._current_page)
        except Exception:
            pass

    def push_screen(self, screen, callback=None):
        if isinstance(screen, str):
            if screen == "pr_detail" and callback and self._client:
                pr_number = callback.get("pr_number", 0)
                head_sha = callback.get("head_sha", "")
                detail_screen = PRDetailScreen(
                    pr_number,
                    self._client,
                    model=self._model,
                    repo=self._repo,
                    head_sha=head_sha,
                )
                return super().push_screen(detail_screen)
            elif screen == "issue_detail" and callback and self._client:
                issue_number = callback.get("issue_number", 0)
                detail_screen = IssueDetailScreen(
                    issue_number, self._client, model=self._model, repo=self._repo
                )
                return super().push_screen(detail_screen)
        return super().push_screen(screen, callback)
