from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Footer, Header, TabbedContent, TabPane


class UbiApp(App):
    """Static layout for the Ubiquiti UMR monitor."""

    CSS = """
    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 0 1;
    }

    DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("f", "filter", "Filter"),
        ("question_mark", "help", "Help"),
        ("m", "toggle_dark", "Toggle dark mode"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="workspaces"):
            with TabPane("Workspaces", id="workspaces"):
                yield DataTable(id="workspace-table", cursor_type="row")
            with TabPane("Devices", id="devices"):
                yield DataTable(id="device-table", cursor_type="row")
            with TabPane("Clients", id="clients"):
                yield DataTable(id="client-table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Ubiquiti UMR Monitor"
        self.sub_title = "Static layout"

        workspaces = self.query_one("#workspace-table", DataTable)
        workspaces.add_columns("Name", "Status", "Devices", "Clients")
        workspaces.add_rows(
            [
                ("whagstrom's Cloud", "ACTIVE", "0", "0"),
                ("Netagen's Cloud", "ACTIVE", "2", "2"),
                ("Szokoly's Cloud", "ACTIVE", "1", "1"),
            ]
        )

        devices = self.query_one("#device-table", DataTable)
        devices.add_columns(
            "Name".ljust(25),
            "WAN IP".ljust(15),
            "State".ljust(5),
            "WAN".ljust(3), 
            "Signal".ljust(6),
            "Usage".rjust(9)
        )
        devices.add_rows(
            [
                ("CBE Vista Heights", "192.168.78.5", "🟢", "WAN", "▁▂▃▅▇█", "0.74"),
                ("CSSD Living Spirit", "10.0.0.2", "🔴", "LTE", "▁▂▃", "0.12"),
                ("CBE St. Andrews Heights", "172.16.1.1", "🟢", "WAN", "▁▂▃▅█", "0.54"),
            ]
        )

        clients = self.query_one("#client-table", DataTable)
        clients.add_columns(
            "Name".ljust(25),
            "IP Address".ljust(15),
            "Status".ljust(6),
            "Type".ljust(4),
            "MAC Address".ljust(17)
        )
        clients.add_rows(
            [
                ("", "192.168.105.154", "🟢", "🖥️", "ec:74:d7:ec:ec:ec"),
                ("pc1", "192.168.105.54", "🔴", "🛜", "d4:e9:8a:d4:d4:d4"),
                ("pc2", "192.168.105.51", "🟢", "🛜", "8c:b8:7e:0a:0a:0a"),
            ]
        )

    def action_refresh(self) -> None:
        self.notify("Static layout: no data refresh configured.")

    def action_filter(self) -> None:
        self.notify("Static layout: filtering is not configured.")
