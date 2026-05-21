"""Pull request list view."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container
from textual.widget import Widget
from textual.widgets import LoadingIndicator, Static
from textual.worker import Worker, WorkerState

from gitnit.cache import get_cached_pr_list, save_pr_list
from gitnit.models import PRData
from gitnit.sorting import sort_prs
from gitnit.widgets.paginated_table import PaginatedTable

if TYPE_CHECKING:
    from gitnit.github_client import GitHubClient


SIZE_COLORS = {
    "XS": "[green]XS[/green]",
    "S": "[green]S[/green]",
    "M": "[yellow]M[/yellow]",
    "L": "[red]L[/red]",
    "XL": "[bold red]XL[/bold red]",
}


class PRListView(Widget):
    """View showing a paginated list of pull requests."""

    DEFAULT_CSS = """
    PRListView {
        height: 1fr;
    }

    PRListView .loading-container {
        align: center middle;
        height: 1fr;
    }
    """

    def __init__(
        self,
        github_client: GitHubClient,
        repo: str = "",
        cache_max_age_seconds: int = 600,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._client = github_client
        self._repo = repo
        self._cache_max_age_seconds = cache_max_age_seconds
        self._prs: list[PRData] = []
        self._current_page = 0
        self._total_count = 0
        self._per_page = 15
        self._loading = True

    def compose(self) -> ComposeResult:
        with Container(classes="loading-container", id="pr-loading"):
            yield LoadingIndicator()
            yield Static("Loading pull requests...", id="pr-loading-text")
        yield PaginatedTable(id="pr-table")

    def on_mount(self) -> None:
        table_widget = self.query_one("#pr-table", PaginatedTable)
        table_widget.display = False

        table = table_widget.table
        table.add_columns("PR", "Title", "Author", "Date", "Size")

        cached = (
            get_cached_pr_list(
                self._repo,
                page=0,
                max_age_seconds=self._cache_max_age_seconds,
            )
            if self._repo
            else None
        )
        if cached:
            prs, total = cached
            self._prs = sort_prs(prs)
            self._total_count = total
            self._populate_table()
            self._loading = False
            self._show_loading(False)
            return

        self._load_page(0)

    def _load_page(self, page: int, show_loading: bool = True) -> None:
        if show_loading:
            self._loading = True
            self._show_loading(True)
        self.run_worker(
            partial(self._client.list_prs, page=page, per_page=self._per_page),
            name="fetch_prs",
            exclusive=True,
            thread=True,
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name != "fetch_prs":
            return
        if event.state == WorkerState.SUCCESS and event.worker.result is not None:
            prs, total = event.worker.result
            self._prs = sort_prs(prs)
            self._total_count = total
            self._current_page = self.query_one("#pr-table", PaginatedTable).current_page
            self._populate_table()
            self._loading = False
            self._show_loading(False)
            if self._repo:
                save_pr_list(self._repo, self._current_page, prs, total)
        elif event.state == WorkerState.ERROR:
            self._loading = False
            self._show_loading(False)

    def _show_loading(self, show: bool) -> None:
        try:
            loading = self.query_one("#pr-loading")
            table_widget = self.query_one("#pr-table", PaginatedTable)
            loading.display = show
            table_widget.display = not show
        except Exception:
            pass

    def _populate_table(self) -> None:
        table_widget = self.query_one("#pr-table", PaginatedTable)
        table = table_widget.table
        table.clear()

        import math

        total_pages = max(1, math.ceil(self._total_count / self._per_page))
        table_widget.total_pages = total_pages

        for pr in self._prs:
            author_display = "[bold cyan]BOT[/bold cyan]" if pr.is_dependabot else pr.author
            size_display = SIZE_COLORS.get(pr.size.value, pr.size.value)

            title = pr.title
            if len(title) > 60:
                title = title[:57] + "..."

            date_display = f"[dim]{pr.created_at.strftime('%d/%b')}[/dim]"

            table.add_row(
                f"[dim]#{pr.number}[/dim]",
                title,
                author_display,
                date_display,
                size_display,
                key=str(pr.number),
            )

    def on_paginated_table_page_changed(self, event: PaginatedTable.PageChanged) -> None:
        self._load_page(event.page)

    def on_paginated_table_row_selected(self, event: PaginatedTable.RowSelected) -> None:
        pr_number = int(event.row_key)
        head_sha = ""
        for pr in self._prs:
            if pr.number == pr_number:
                head_sha = pr.head_sha
                break
        self.app.push_screen("pr_detail", {"pr_number": pr_number, "head_sha": head_sha})
