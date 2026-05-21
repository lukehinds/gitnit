"""Paginated DataTable widget for GitNit."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static


class PaginatedTable(Widget):
    """A DataTable with pagination controls."""

    current_page: reactive[int] = reactive(0)
    total_pages: reactive[int] = reactive(1)

    class PageChanged(Message):
        def __init__(self, page: int) -> None:
            self.page = page
            super().__init__()

    class RowSelected(Message):
        def __init__(self, row_key: str) -> None:
            self.row_key = row_key
            super().__init__()

    def compose(self) -> ComposeResult:
        yield DataTable(id="data-table")
        with Horizontal(classes="pagination-bar"):
            yield Button("< Previous", id="btn-prev", variant="default", disabled=True)
            yield Static("Page 1 / 1", id="page-info", classes="page-info")
            yield Button("Next >", id="btn-next", variant="default", disabled=True)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"

    @property
    def table(self) -> DataTable:
        return self.query_one(DataTable)

    def watch_current_page(self) -> None:
        self._update_pagination_ui()

    def watch_total_pages(self) -> None:
        self._update_pagination_ui()

    def _update_pagination_ui(self) -> None:
        try:
            prev_btn = self.query_one("#btn-prev", Button)
            next_btn = self.query_one("#btn-next", Button)
            page_info = self.query_one("#page-info", Static)

            prev_btn.disabled = self.current_page <= 0
            next_btn.disabled = self.current_page >= self.total_pages - 1
            page_info.update(f"Page {self.current_page + 1} / {self.total_pages}")
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-prev" and self.current_page > 0:
            self.current_page -= 1
            self.post_message(self.PageChanged(self.current_page))
        elif event.button.id == "btn-next" and self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.post_message(self.PageChanged(self.current_page))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value is not None:
            self.post_message(self.RowSelected(str(event.row_key.value)))

    def on_key(self, event) -> None:
        table = self.query_one(DataTable)
        if event.key == "down":
            if table.cursor_row >= table.row_count - 1:
                next_btn = self.query_one("#btn-next", Button)
                if not next_btn.disabled:
                    next_btn.focus()
                event.prevent_default()
        elif event.key == "up" and table.cursor_row <= 0:
            prev_btn = self.query_one("#btn-prev", Button)
            if not prev_btn.disabled:
                prev_btn.focus()
            event.prevent_default()
