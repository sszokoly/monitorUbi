"""Formatting for the device dashboard table."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from rich.text import Text


def _status_icon(value: str) -> Text:
    match value:
        case "ACTIVE" | "CONNECTED" | "ONLINE":
            return Text("●", style="green")
        case (
            "PENDING"
            | "ADOPTING"
            | "DOWNLOADING"
            | "UPGRADING"
            | "RESTARTING"
            | "GETTING_READY"
            | "RESTORING"
        ):
            return Text("●", style="yellow")
        case "INACTIVE" | "DISCONNECTED" | "OFFLINE" | "ADOPTING_TIMEOUT":
            return Text("●", style="red")
        case "DECLINED" | "BLOCKED" | "FACTORY_RESET" | "DELETING":
            return Text("●", style="bold red")
        case "NULL":
            return Text("○", style="dim")
        case _:
            return Text("?", style="dim")


def _lte_signal(value: Optional[str]) -> Text:
    match value:
        case "STRONG":
            return Text("▁▂▃▅▇█", style="green")
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


def _format_data_usage(value: int) -> str:
    if value >= 1024**3:
        return f"{value / 1024**3:>5.1f} GB"
    if value >= 1024**2:
        return f"{value / 1024**2:>5.1f} MB"
    return f"{value / 1024:>5.1f} KB"


@dataclass(frozen=True)
class DeviceDashboardViewModel:
    """One joined workspace/device row formatted for the device dashboard."""

    name: str
    workspace_name: str
    state: str
    wan_ip: Optional[str]
    wan_source: Optional[str]
    lte_signal_level: Optional[str]
    cellular_data_usage_bytes: int
    client_count: int
    last_seen_at: str

    @property
    def state_text(self) -> Text:
        return _status_icon(self.state)

    @property
    def wan_ip_text(self) -> str:
        return self.wan_ip or "-"

    @property
    def wan_source_text(self) -> str:
        return self.wan_source or "-"

    @property
    def lte_signal_text(self) -> Text:
        return _lte_signal(self.lte_signal_level)

    @property
    def data_usage_text(self) -> str:
        return _format_data_usage(self.cellular_data_usage_bytes)

    @property
    def last_seen_text(self) -> str:
        observed_at = datetime.fromisoformat(self.last_seen_at)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        return observed_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")

    @property
    def table_row(self) -> tuple[str, str, Text, str, str, Text, str, str, str]:
        return (
            self.name,
            self.workspace_name,
            self.state_text,
            self.wan_ip_text,
            self.wan_source_text,
            self.lte_signal_text,
            self.data_usage_text,
            str(self.client_count),
            self.last_seen_text,
        )
