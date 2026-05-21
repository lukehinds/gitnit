"""Issue list view."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import LoadingIndicator, Static
from textual.worker import Worker, WorkerState

from reviewsage.cache import get_cached_issue_list, save_issue_list
from reviewsage.models import IssueData, IssueLabel
from reviewsage.widgets.paginated_table import PaginatedTable

if TYPE_CHECKING:
    from reviewsage.github_client import GitHubClient

LABEL_INDICATORS = {
    IssueLabel.BUG: "[red]||[/red]",
    IssueLabel.QUESTION: "[green]||[/green]",
    IssueLabel.ENHANCEMENT: "[dodger_blue2]||[/dodger_blue2]",
    IssueLabel.FEATURE: "[medium_purple]||[/medium_purple]",
    IssueLabel.OTHER: "[dim]||[/dim]",
}


class IssueListView(Widget):
    """View showing a paginated list of issues."""

    DEFAULT_CSS = """
    IssueListView {
        height: 1fr;
    }

    IssueListView .loading-container {
        align: center middle;
        height: 1fr;
    }
    """

    sort_newest: reactive[bool] = reactive(True)

    def __init__(self, github_client: GitHubClient, repo: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._client = github_client
        self._repo = repo
        self._issues: list[IssueData] = []
        self._current_page = 0
        self._total_count = 0
        self._per_page = 15
        self._loading = True

    def compose(self) -> ComposeResult:
        yield Static("", id="issue-sort-indicator", classes="sort-indicator")
        with Container(classes="loading-container", id="issue-loading"):
            yield LoadingIndicator()
            yield Static("Loading issues...", id="issue-loading-text")
        yield PaginatedTable(id="issue-table")

    def on_mount(self) -> None:
        table_widget = self.query_one("#issue-table", PaginatedTable)
        table_widget.display = False

        table = table_widget.table
        table.add_columns("#", "Title", "Author", "Date", "Label")

        self._update_sort_indicator()

        direction = "desc" if self.sort_newest else "asc"
        cached = get_cached_issue_list(self._repo, page=0, direction=direction) if self._repo else None
        if cached:
            issues, total = cached
            self._issues = issues
            self._total_count = total
            self._populate_table()
            self._loading = False
            self._show_loading(False)

        self._load_page(0, show_loading=cached is None)

    def _update_sort_indicator(self) -> None:
        order = "Newest first" if self.sort_newest else "Oldest first"
        try:
            indicator = self.query_one("#issue-sort-indicator", Static)
            indicator.update(f" Sort: {order}  [dim](press 's' to toggle)[/dim]")
        except Exception:
            pass

    def watch_sort_newest(self) -> None:
        self._update_sort_indicator()
        self._load_page(0)

    def _load_page(self, page: int, show_loading: bool = True) -> None:
        if show_loading:
            self._loading = True
            self._show_loading(True)
        direction = "desc" if self.sort_newest else "asc"
        self.run_worker(
            self._fetch_issues(page, direction),
            name="fetch_issues",
            exclusive=True,
        )

    async def _fetch_issues(self, page: int, direction: str) -> tuple[list[IssueData], int]:
        return self._client.list_issues(page=page, per_page=self._per_page, direction=direction)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name != "fetch_issues":
            return
        if event.state == WorkerState.SUCCESS and event.worker.result is not None:
            issues, total = event.worker.result
            self._issues = issues
            self._total_count = total
            self._populate_table()
            self._loading = False
            self._show_loading(False)
            if self._repo:
                direction = "desc" if self.sort_newest else "asc"
                page = self.query_one("#issue-table", PaginatedTable).current_page
                save_issue_list(self._repo, page, issues, total, direction=direction)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._show_loading(False)

    def _show_loading(self, show: bool) -> None:
        try:
            loading = self.query_one("#issue-loading")
            table_widget = self.query_one("#issue-table", PaginatedTable)
            loading.display = show
            table_widget.display = not show
        except Exception:
            pass

    def _populate_table(self) -> None:
        table_widget = self.query_one("#issue-table", PaginatedTable)
        table = table_widget.table
        table.clear()

        total_pages = max(1, math.ceil(self._total_count / self._per_page))
        table_widget.total_pages = total_pages

        for issue in self._issues:
            label_display = LABEL_INDICATORS.get(issue.label, "[dim]||[/dim]")
            label_text = f"{label_display} {issue.label_raw}" if issue.label_raw else label_display

            title = issue.title
            if len(title) > 60:
                title = title[:57] + "..."

            date_display = f"[dim]{issue.created_at.strftime('%d/%b')}[/dim]"

            table.add_row(
                f"[dim]#{issue.number}[/dim]",
                title,
                issue.author,
                date_display,
                label_text,
                key=str(issue.number),
            )

    def on_paginated_table_page_changed(self, event: PaginatedTable.PageChanged) -> None:
        self._load_page(event.page)

    def on_paginated_table_row_selected(self, event: PaginatedTable.RowSelected) -> None:
        issue_number = int(event.row_key)
        self.app.push_screen("issue_detail", {"issue_number": issue_number})

    def toggle_sort(self) -> None:
        self.sort_newest = not self.sort_newest
