import asyncio
import re

from rich.text import Text
from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static
from monitorUbi.client import MobilityApiClient
from monitorUbi.daemon import run_daemon
from monitorUbi.db import SqliteSnapshotStore, database_size
from monitorUbi.service import MonitorService, SyncSummary
from monitorUbi.utils import memory_usage
from monitorUbi.view_models import DeviceDashboardViewModel


class FilterScreen(ModalScreen[str | None]):
    """Collect and validate a device-table regular expression."""

    CSS = """
    FilterScreen {
        align: center middle;
    }

    #filter-dialog {
        width: 60;
        max-width: 90%;
        height: 3;
        border: round $primary;
        background: $surface;
        padding: 0 1;
    }

    #filter-input {
        height: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, filter_text: str) -> None:
        super().__init__()
        self._filter_text = filter_text

    def compose(self) -> ComposeResult:
        with Container(id="filter-dialog") as dialog:
            dialog.border_title = "Regex Search"
            yield Input(
                self._filter_text,
                id="filter-input",
                placeholder="Enter a regular expression",
                compact=True,
            )

    def on_mount(self) -> None:
        self.query_one("#filter-input", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_search(self) -> None:
        filter_text = self.query_one("#filter-input", Input).value.strip()
        try:
            if filter_text:
                re.compile(filter_text, re.IGNORECASE)
        except re.error as error:
            self.app.notify(
                f"Invalid regular expression: {error}", severity="error"
            )
            return
        self.dismiss(filter_text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter-input":
            self.action_search()


class UbiApp(App):
    """Monitoring dashboard for Ubiquiti UMR devices."""

    CSS = """
    #service-panel {
        height: 3;
        border: round $primary;
        padding: 0 1;
    }

    #devices-panel {
        height: 1fr;
        border: round $primary;
        padding: 0 1;
    }

    #device-table {
        height: 1fr;
    }

    #device-table > .datatable--header {
        color: #00e5ee;
        background: $panel;
        text-style: bold;
    }

    #device-table:focus {
        background-tint: $foreground 0%;
    }

    #device-table > .datatable--cursor {
        background: $primary 10%;
    }

    #device-table:focus > .datatable--cursor {
        background: $primary 20%;
    }

    #footer-menu {
        height: 1;
        padding: 0 1;
        color: $footer-foreground;
        background: $footer-background;
    }
    """

    BINDINGS = [
        ("s", "toggle_service", "Start/Stop"),
        ("q", "quit", "Quit"),
        ("f", "filter", "Filter"),
        ("enter", "details", "Details"),
    ]

    service_running = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self._store = SqliteSnapshotStore()
        self._api_client: MobilityApiClient | None = None
        self._daemon_stop_event: asyncio.Event | None = None
        self._daemon_task: asyncio.Task[None] | None = None
        self._filter_text = ""
        self._filter_pattern: re.Pattern[str] | None = None

    def compose(self) -> ComposeResult:
        service_panel = Container(
            Static(self.service_status_text(), id="service-status"),
            id="service-panel",
        )
        service_panel.border_title = "monitorUbi"
        yield service_panel

        devices_panel = Container(
            DataTable(
                id="device-table",
                cursor_type="row",
                cursor_foreground_priority="renderable",
                cursor_background_priority="css",
                show_row_labels=False,
                cell_padding=2,
            ),
            id="devices-panel",
        )
        devices_panel.border_title = "Devices"
        yield devices_panel
        yield Static(self.footer_text(), id="footer-menu")

    def service_status_text(self) -> Text:
        """Build the Rich status line from the current service state."""
        status_icon = "√" if self.service_running else "X"
        status_label = "running" if self.service_running else "stopped"
        status_style = "green1" if self.service_running else "red1"
        workspace_count = self._store.workspace_count
        device_count = self._store.device_count
        client_count = self._store.online_client_count
        history_days = self._store.history_days

        return Text.assemble(
            ("Status: ", "grey70"),
            (status_icon, f"bold {status_style}"),
            (f" ({status_label})", status_style),
            (" | Service: ", "grey70"),
            (
                "enabled " if self.service_running else "disabled",
                "green1" if self.service_running else "yellow",
            ),
            (" | RAM Usage: ", "grey70"),
            (f"{memory_usage()} MB", "turquoise2"),
            (" | DB Size: ", "grey70"),
            (f"{database_size()}", "turquoise2"),
            (" | Workspaces: ", "grey70"),
            (f"{workspace_count}", "turquoise2"),
            (" | Devices: ", "grey70"),
            (f"{device_count}", "turquoise2"),
            (" | Clients: ", "grey70"),
            (f"{client_count}", "turquoise2"),
            (" | History (days): ", "grey70"),
            (f"{history_days}", "turquoise2"),
        )

    def footer_text(self) -> Text:
        """Build the footer menu with the action for the current service state."""
        service_action = "Stop " if self.service_running else "Start"
        return Text.assemble(
            ("s", "bold cyan"),
            (f"={service_action}  ", ""),
            ("q", "bold cyan"),
            ("=Quit  ", ""),
            ("f", "bold cyan"),
            ("=Filter  ", ""),
            ("Enter", "bold cyan"),
            ("=Details", ""),
        )

    async def on_mount(self) -> None:
        self.title = "monitorUbi"
        self.console.options.legacy_windows = False

        devices = self.query_one("#device-table", DataTable)
        devices.add_column("Name", width=30)
        devices.add_column("Workspace", width=20)
        devices.add_column("State", width=5)
        devices.add_column("WAN-IP", width=15)
        devices.add_column("WAN", width=3)
        devices.add_column("Signal", width=6)
        devices.add_column("Usage", width=10)
        devices.add_column("Clients", width=7)
        devices.add_column("Last-Seen", width=19)
        await self._store.refresh_current_counts()
        await self._store.refresh_history_days()
        self.query_one("#service-status", Static).update(
            self.service_status_text()
        )
        await self.refresh_device_table()

    async def refresh_device_table(self) -> None:
        """Load persisted device data and format it for the dashboard table."""
        rows = await self._store.get_device_dashboard_rows()
        view_models = [DeviceDashboardViewModel(**row) for row in rows]
        filtered_view_models = [
            view_model
            for view_model in view_models
            if self._filter_pattern is None
            or any(
                self._filter_pattern.search(value)
                for value in (
                    view_model.name,
                    view_model.workspace_name,
                    view_model.wan_ip or "",
                )
            )
        ]

        table = self.query_one("#device-table", DataTable)
        table.clear()
        table.add_rows(view_model.table_row for view_model in filtered_view_models)

    async def action_toggle_service(self) -> None:
        if self.service_running:
            await self._stop_monitor_runner()
        else:
            await self._start_monitor_runner()

    async def _start_monitor_runner(self) -> None:
        try:
            api_client = MobilityApiClient()
        except ValueError as error:
            self.notify(str(error), severity="error")
            return

        stop_event = asyncio.Event()
        service = MonitorService(
            api_client,
            self._store,
            on_refresh=self._refresh_after_sync,
        )
        self._api_client = api_client
        self._daemon_stop_event = stop_event
        self._daemon_task = asyncio.create_task(
            run_daemon(service, stop_event),
            name="monitorubi-tui-runner",
        )
        self.service_running = True

    async def _stop_monitor_runner(self) -> None:
        daemon_task = self._daemon_task
        stop_event = self._daemon_stop_event
        api_client = self._api_client

        if stop_event is not None:
            stop_event.set()

        try:
            if daemon_task is not None:
                await daemon_task
        finally:
            if api_client is not None:
                await api_client.aclose()
            self._api_client = None
            self._daemon_stop_event = None
            self._daemon_task = None
            self.service_running = False

    async def _refresh_after_sync(self, _: SyncSummary) -> None:
        try:
            await self.refresh_device_table()
        except Exception as error:
            self.notify(f"Dashboard refresh failed: {error}", severity="error")

    async def on_unmount(self) -> None:
        await self._stop_monitor_runner()

    def watch_service_running(self) -> None:
        """Refresh service-state displays after the reactive value changes."""
        try:
            self.query_one("#service-status", Static).update(self.service_status_text())
            self.query_one("#footer-menu", Static).update(self.footer_text())
        except NoMatches:
            # Reactive values initialize before compose() has mounted these widgets.
            return

    def action_filter(self) -> None:
        self.push_screen(FilterScreen(self._filter_text), self._apply_device_filter)

    async def _apply_device_filter(self, filter_text: str | None) -> None:
        """Apply a validated filter returned by the filter dialog."""
        if filter_text is None:
            return

        self._filter_text = filter_text
        self._filter_pattern = (
            re.compile(filter_text, re.IGNORECASE) if filter_text else None
        )
        await self.refresh_device_table()

    def action_details(self) -> None:
        self.notify("Static dashboard: device details are not configured.")
