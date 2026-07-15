from dataclasses import dataclass
from typing import Optional

from rich.text import Text

from monitorUbi.schemas import Device, DeviceClient, Workspace


def _status_icon(value: str) -> Text:
    match value:
        case "ACTIVE" | "CONNECTED" | "ONLINE":
            return Text("🟢", style="green")
        case (
            "PENDING"
            | "ADOPTING"
            | "DOWNLOADING"
            | "UPGRADING"
            | "RESTARTING"
            | "GETTING_READY"
            | "RESTORING"
        ):
            return Text("🟡", style="yellow")
        case "INACTIVE" | "DISCONNECTED" | "OFFLINE" | "ADOPTING_TIMEOUT":
            return Text("🔴", style="red")
        case "DECLINED" | "BLOCKED" | "FACTORY_RESET" | "DELETING":
            return Text("⛔", style="bold red")
        case "NULL":
            return Text("⚪", style="dim")
        case _:
            return Text("?", style="dim")


def _lte_signal(value: Optional[str]) -> Text:
    match value:
        case "STRONG":
            return Text("▁▂▃▅▇█", style="cyan")
        case "FAIR":
            return Text("▁▂▃▅", style="yellow")
        case "POOR":
            return Text("▁▂▃", style="red")
        case "NO_SIGNAL":
            return Text("-", style="dim red")
        case "" | None:
            return Text("-", style="dim")
        case _:
            return Text("?", style="dim")


@dataclass(frozen=True)
class WorkspaceViewModel:
    workspace: Workspace
    device_count: int = 0
    client_count: int = 0

    @property
    def name(self) -> str:
        return self.workspace.workspace_name

    @property
    def status(self) -> str:
        return self.workspace.status

    @property
    def status_text(self) -> Text:
        return _status_icon(self.workspace.status)

    @property
    def table_row(self) -> tuple[str, str, str, str]:
        return (
            self.name,
            self.status,
            str(self.device_count),
            str(self.client_count),
        )


@dataclass(frozen=True)
class DeviceViewModel:
    device: Device

    @property
    def state_text(self) -> Text:
        return _status_icon(self.device.state)

    @property
    def wan_ip(self) -> str:
        return str(self.device.wan_ip or "-")

    @property
    def lte_signal_text(self) -> Text:
        return _lte_signal(self.device.lte_signal_level)

    @property
    def cellular_data_usage_mb(self) -> str:
        return f"{self.device.cellular_data_usage_bytes / 1024 / 1024:.2f}"

    @property
    def table_row(self) -> tuple[str, str, Text, str, Text, str]:
        return (
            self.device.name,
            self.wan_ip,
            self.state_text,
            self.device.wan_source,
            self.lte_signal_text,
            self.cellular_data_usage_mb,
        )


@dataclass(frozen=True)
class DeviceClientViewModel:
    client: DeviceClient

    @property
    def name(self) -> str:
        return self.client.name or ""

    @property
    def ip_address(self) -> str:
        return str(self.client.ip_address or "-")

    @property
    def status_text(self) -> Text:
        return _status_icon(self.client.connection_status)

    @property
    def type_text(self) -> Text:
        match self.client.type:
            case "WIRED":
                return Text("💻", style="deep_sky_blue1")
            case "WIRELESS":
                return Text("🛜", style="orange1")
            case _:
                return Text(self.client.type, style="dim")

    @property
    def table_row(self) -> tuple[str, str, Text, Text, str]:
        return (
            self.name,
            self.ip_address,
            self.status_text,
            self.type_text,
            self.client.mac,
        )
