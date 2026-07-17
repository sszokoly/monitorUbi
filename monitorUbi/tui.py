from rich.text import Text
from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.containers import Container
from textual.widgets import DataTable, Static
from textual.reactive import reactive
from monitorUbi.utils import memory_usage

class UbiApp(App):
    """Static monitoring dashboard for Ubiquiti UMR devices."""

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
    service_enabled = reactive(False)

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
        status_style = "green" if self.service_running else "red"
        ram = memory_usage()

        return Text.assemble(
            ("Status: ", "bold"),
            (status_icon, f"bold {status_style}"),
            (f" ({status_label})", status_style),
            (" | Service: ", "bold"),
            ("disabled", "yellow"),
            (f" | RAM Usage: {ram} MB"),
            (" | DB Size: 200 MB | Workspaces: 99 | Devices: 323 ", ""),
            ("| Clients: 323 | History: 30 days", ""),
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

    def on_mount(self) -> None:
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
        devices.add_column("Last-Updated", width=19)
        devices.add_row(
            "CBE St. Andrews Heights",
            "whagstrom's Cloud",
            Text(" ● ", style="green"),
            "192.168.178.125",
            "LTE",
            Text("▁▂▃▅▇█", style="green"),
            "999.12 MB",
            "1",
            "2026-10-12 18:12:32",
        )
        devices.add_row(
            "CBE Vista Heights",
            "whagstrom's Cloud",
            Text(" ● ", style="green"),
            "192.168.178.126",
            "WAN",
            Text("▁▂▃▅", style="orange1"),
            " 99.12 MB",
            "1",
            "2026-10-12 18:12:32",
        )
        devices.add_row(
            "CBE Montain Park",
            "whagstrom's Cloud",
            Text(" ● ", style="red"),
            "192.168.178.126",
            "-",
            Text("-", style="red"),
            "  1.01 GB",
            "1",
            "2026-10-12 18:15:32",
        )

    def action_toggle_service(self) -> None:
        self.service_running = not self.service_running

    def watch_service_running(self) -> None:
        """Refresh service-state displays after the reactive value changes."""
        try:
            self.query_one("#service-status", Static).update(self.service_status_text())
            self.query_one("#footer-menu", Static).update(self.footer_text())
        except NoMatches:
            # Reactive values initialize before compose() has mounted these widgets.
            return

    def action_filter(self) -> None:
        self.notify("Static dashboard: filtering is not configured.")

    def action_details(self) -> None:
        self.notify("Static dashboard: device details are not configured.")
