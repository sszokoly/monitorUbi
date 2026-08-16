import asyncio
import os
import re
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from math import log10

from rich.style import Style
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Input, Static
from textual_hires_canvas import Canvas, TextAlign
from textual_plot import HiResMode, NumericAxisFormatter, PlotWidget
from monitorUbi.client import MobilityApiClient
from monitorUbi.config import get_setting, load_config
from monitorUbi.db import (
    DEFAULT_DATABASE_PATH,
    SqliteSnapshotStore,
    configured_database_path,
    database_size,
)
from monitorUbi.service import MonitorService, SyncSummary
from monitorUbi.systemd import SystemdError, SystemdService
from monitorUbi.utils import memory_usage, uptime_seconds_to_string
from monitorUbi.view_models import DeviceDashboardViewModel


_DETAIL_LABEL_STYLE = Style(color="grey70", bold=False)
_DETAIL_VALUE_STYLE = Style(color="turquoise2", bold=False)
_SIGNAL_LEVELS = {"NO_SIGNAL": 0, "POOR": 1, "FAIR": 2, "STRONG": 3}
_SIGNAL_STYLES = {
    "NO_SIGNAL": "red1",
    "POOR": "orange1",
    "FAIR": "yellow",
    "STRONG": "green1",
}
DEFAULT_DASHBOARD_REFRESH_INTERVAL_SECONDS = 5.0
_IS_LINUX = sys.platform.startswith("linux")
_OBSERVER_MODE = os.getenv("MONITORUBI_TUI_MODE", "").lower() == "observer"
_SYSTEMD_AVAILABLE = _IS_LINUX and os.getenv("MONITORUBI_DISABLE_SYSTEMD") != "1"


def _dashboard_refresh_interval_seconds() -> float:
    """Return the configured dashboard refresh interval."""
    config, _ = load_config()
    interval = float(
        get_setting(
            config,
            "tui",
            "dashboard_refresh_interval_seconds",
            DEFAULT_DASHBOARD_REFRESH_INTERVAL_SECONDS,
        )
    )
    if interval <= 0:
        raise ValueError("dashboard_refresh_interval_seconds must be greater than 0")
    return interval


def _usage_tick_bytes(maximum: int) -> list[int]:
    """Return fixed byte references through the next value above maximum."""
    ticks = [0]
    unit = 1024
    minimum_maximum = 10 * 1024**2
    while True:
        for multiplier in (1, 10, 100):
            tick = unit * multiplier
            ticks.append(tick)
            if tick >= max(maximum, minimum_maximum):
                return ticks
        unit *= 1024


def _format_usage_tick(value: int) -> str:
    """Format a fixed Usage-axis reference value."""
    if value == 0:
        return "0 KB"
    if value >= 1024**3:
        return f"{value / 1024**3:g} GB"
    if value >= 1024**2:
        return f"{value / 1024**2:g} MB"
    return f"{value / 1024:g} KB"


class _LocalTimestampFormatter(NumericAxisFormatter):
    """Format epoch-second ticks using local time."""

    def get_labels_for_ticks(self, ticks: Sequence[float]) -> list[str]:
        return [
            datetime.fromtimestamp(tick, timezone.utc).astimezone().strftime("%H:%M")
            for tick in ticks
        ]


class _SignalLevelFormatter(NumericAxisFormatter):
    """Format fixed LTE signal levels rather than arbitrary numeric ticks."""

    _labels = {0: "No Signal", 1: "Poor", 2: "Fair", 3: "Strong"}

    def get_ticks(self, min_: float, max_: float, max_ticks: int = 8) -> list[float]:
        return [float(level) for level in range(4)]

    def get_labels_for_ticks(self, ticks: Sequence[float]) -> list[str]:
        return [self._labels.get(round(tick), "") for tick in ticks]


class _UsageByteFormatter(NumericAxisFormatter):
    """Format fixed log10(byte_count + 1) positions as byte references."""

    def __init__(self, tick_bytes: list[int]) -> None:
        self._tick_bytes = tick_bytes
        self._tick_positions = [log10(value + 1) for value in tick_bytes]

    def get_ticks(self, min_: float, max_: float, max_ticks: int = 8) -> list[float]:
        return self._tick_positions

    def get_labels_for_ticks(self, ticks: Sequence[float]) -> list[str]:
        return [
            _format_usage_tick(
                self._tick_bytes[
                    min(
                        range(len(self._tick_positions)),
                        key=lambda index: abs(self._tick_positions[index] - tick),
                    )
                ]
            )
            for tick in ticks
        ]


class _DateBoundedPlot(PlotWidget):
    """Plot widget with bounded horizontal navigation and date-aware X labels."""

    def __init__(
        self,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        *,
        allow_pan_and_zoom: bool = True,
        invert_mouse_wheel: bool = False,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            name,
            id,
            classes,
            allow_pan_and_zoom=allow_pan_and_zoom,
            invert_mouse_wheel=invert_mouse_wheel,
            disabled=disabled,
        )
        self._sampled_at_min: float | None = None
        self._sampled_at_max: float | None = None

    def set_sampled_at_bounds(self, minimum: float, maximum: float) -> None:
        """Set the available sample-time range used to clamp navigation."""
        self._sampled_at_min = minimum
        self._sampled_at_max = maximum

    def capture_x_viewport(self) -> tuple[float, float, bool] | None:
        """Capture the visible range and whether it follows the newest sample."""
        if self._sampled_at_max is None:
            return None
        return self._x_min, self._x_max, self._x_max >= self._sampled_at_max

    def restore_x_viewport(self, viewport: tuple[float, float, bool]) -> None:
        """Restore a manually panned range inside the current sample bounds."""
        minimum, maximum, follows_latest = viewport
        if follows_latest:
            return
        self.set_xlimits(minimum, maximum)
        self._clamp_x_limits()

    def _render_plot(self) -> None:
        """Render the base plot without its top frame edge or top tick marks."""
        super()._render_plot()
        try:
            canvas = self.query_one("#plot", Canvas)
        except NoMatches:
            return
        for x in range(canvas.size.width):
            canvas.set_pixel(x, 0, " ", style="")
        for y in range(canvas.size.height):
            canvas.set_pixel(canvas.size.width - 1, y, " ", style="")

    def action_pan_up(self) -> None:
        """Disable vertical panning for the fixed chart scale."""

    def action_pan_down(self) -> None:
        """Disable vertical panning for the fixed chart scale."""

    def _pan(self, factor_x: float, factor_y: float) -> None:
        """Pan horizontally only, keeping the view inside available samples."""
        if factor_x == 0 or self._sampled_at_min == self._sampled_at_max:
            return
        super()._pan(factor_x, 0)
        self._clamp_x_limits()
        self._rerender()

    def _zoom(
        self,
        center_x: float,
        center_y: float,
        factor: float,
        zoom_x: bool,
        zoom_y: bool,
    ) -> None:
        """Zoom horizontally only and prevent zooming past sample-time bounds."""
        if self._sampled_at_min == self._sampled_at_max:
            return
        super()._zoom(center_x, center_y, factor, zoom_x, False)
        self._clamp_x_limits()
        self._rerender()

    def _clamp_x_limits(self) -> None:
        """Constrain the visible range to the oldest and newest sampled_at values."""
        if self._sampled_at_min is None or self._sampled_at_max is None:
            return

        available_width = self._sampled_at_max - self._sampled_at_min
        visible_width = self._x_max - self._x_min
        if visible_width >= available_width:
            self._x_min = self._sampled_at_min
            self._x_max = self._sampled_at_max
        elif self._x_min < self._sampled_at_min:
            self._x_max += self._sampled_at_min - self._x_min
            self._x_min = self._sampled_at_min
        elif self._x_max > self._sampled_at_max:
            self._x_min -= self._x_max - self._sampled_at_max
            self._x_max = self._sampled_at_max

    def _render_x_ticks(self) -> None:
        canvas = self.query_one("#plot", Canvas)
        bottom_margin = self.query_one("#margin-bottom", Canvas)
        bottom_margin.reset()
        if self._x_ticks is None:
            x_ticks, time_labels = self._x_formatter.get_ticks_and_labels(
                self._x_min, self._x_max
            )
        else:
            x_ticks = self._x_ticks
            time_labels = self._x_formatter.get_labels_for_ticks(x_ticks)
        previous_date = None

        for tick, time_label in zip(x_ticks, time_labels):
            if tick < self._x_min or tick > self._x_max:
                continue

            align = TextAlign.CENTER
            x, _ = self.get_pixel_from_coordinate(tick, 0.0)
            if tick == self._x_min:
                x -= 1
            elif tick == self._x_max:
                align = TextAlign.RIGHT

            for y, quad in (
                (0, (2, 0, 0, 0)),
                (self._scale_rectangle.bottom, (0, 0, 2, 0)),
            ):
                pixel = self.combine_quad_with_pixel(quad, canvas, x, y)
                canvas.set_pixel(
                    x,
                    y,
                    pixel,
                    style=str(self.get_component_rich_style("plot--axis")),
                )

            tick_style = self.get_component_rich_style("plot--tick")
            bottom_margin.write_text(
                x + self.margin_left,
                0,
                f"[{tick_style}]{time_label}",
                align,
            )
            tick_date = datetime.fromtimestamp(tick, timezone.utc).astimezone().date()
            if tick_date != previous_date:
                bottom_margin.write_text(
                    x + self.margin_left,
                    1,
                    f"[{tick_style}]{tick_date.isoformat()}",
                    align,
                )
                previous_date = tick_date

    def _render_x_label(self) -> None:
        """Suppress the base X-axis title; time and date labels are sufficient."""


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
            dialog.border_title = "Search"
            yield Input(
                self._filter_text,
                id="filter-input",
                placeholder="Enter a string or regular expression",
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


class ConfirmationScreen(ModalScreen[bool]):
    """Ask for a one-line keyboard confirmation before changing service state."""

    CSS = """
    ConfirmationScreen {
        align: center middle;
    }

    #confirmation-dialog {
        width: 60;
        max-width: 90%;
        height: 4;
        border: round $warning;
        background: $surface;
        padding: 0 1;
        align: center middle;
    }

    #confirmation-message {
        width: 100%;
        height: 1;
        content-align: center middle;
        text-align: center;
    }

    #confirmation-ok {
        width: 6;
        min-width: 6;
        max-width: 6;
        height: 1;
    }

    #confirmation-actions {
        width: 100%;
        height: 1;
        align: center middle;
    }
    """

    BINDINGS = [("enter", "confirm", "Confirm"), ("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Container(id="confirmation-dialog") as dialog:
            dialog.border_title = "Confirm"
            yield Static(self._prompt, id="confirmation-message")
            with Horizontal(id="confirmation-actions"):
                yield Button(
                    "OK", id="confirmation-ok", variant="primary", compact=True
                )

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirmation-ok":
            self.action_confirm()


class SudoPasswordScreen(ModalScreen[str | None]):
    """Collect a sudo password without retaining or rendering its value."""

    CSS = """
    SudoPasswordScreen {
        align: center middle;
    }

    #sudo-dialog {
        width: 60;
        max-width: 90%;
        height: 4;
        border: round $primary;
        background: $surface;
        padding: 0 1;
    }

    #sudo-password {
        height: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container(id="sudo-dialog") as dialog:
            dialog.border_title = "Administrator Password"
            yield Input(
                placeholder="Enter sudo password, then press Enter",
                password=True,
                compact=True,
                id="sudo-password",
            )

    def on_mount(self) -> None:
        self.query_one("#sudo-password", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "sudo-password":
            self.dismiss(event.value)


class DeviceDetailsScreen(Screen):
    """Show current device data alongside empty plot hosts."""

    HORIZONTAL_BREAKPOINTS = [(120, "wide")]

    CSS = """
    DeviceDetailsScreen {
        layout: vertical;
    }

    DeviceDetailsScreen.wide {
        layout: grid;
        grid-size: 3 2;
        grid-columns: 1fr 1fr 1fr;
        grid-rows: 1fr 1fr;
    }

    .details-panel {
        height: 1fr;
        border: round $primary;
        padding: 0;
    }

    DeviceDetailsScreen.wide #details-device {
        row-span: 2;
    }

    DeviceDetailsScreen.wide #details-signal,
    DeviceDetailsScreen.wide #details-usage {
        column-span: 2;
    }

    #signal-plot,
    #usage-plot {
        width: 100%;
        height: 100%;
    }

    #signal-plot > .plot--label,
    #signal-plot > .plot--tick,
    #usage-plot > .plot--label,
    #usage-plot > .plot--tick {
        color: lightgrey;
        text-style: none;
    }

    #signal-plot > .plot--tick,
    #usage-plot > .plot--tick {
        color: #b3b3b3;
    }

    #signal-plot > .plot--axis,
    #usage-plot > .plot--axis {
        color: #b3b3b3;
    }
    """

    BINDINGS = [
        ("enter", "back", "Back"),
        ("escape", "back", "Back"),
        ("q", "ignore_quit", ""),
    ]

    def __init__(self, store: SqliteSnapshotStore, device_id: str) -> None:
        super().__init__()
        self._store = store
        self._device_id = device_id
        self._plots_ready = False
        self._signal_latest_sampled_at: str | None = None
        self._usage_latest_sampled_at: str | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(
            id="details-device", classes="details-panel"
        ) as device_panel:
            device_panel.border_title = "Device"
            yield Static(id="device-details")

        with Container(id="details-signal", classes="details-panel") as signal_panel:
            signal_panel.border_title = "LTE Signal Level"
            yield _DateBoundedPlot(id="signal-plot")

        with Container(id="details-usage", classes="details-panel") as usage_panel:
            usage_panel.border_title = "Cellular Data Usage"
            yield _DateBoundedPlot(id="usage-plot")

    async def on_mount(self) -> None:
        for plot in self.query(PlotWidget):
            plot.margin_top = 0
            plot.margin_left = 10
        self.query_one("#signal-plot", PlotWidget).margin_bottom = 2
        self.query_one("#usage-plot", PlotWidget).margin_bottom = 2
        await self._load_device_details()
        self.call_after_refresh(self._initialize_plots)

    async def _load_device_details(self) -> None:
        details = await self._store.get_device_details(self._device_id)
        content = self.query_one("#device-details", Static)
        if details is None:
            content.update(Text("Device is no longer available.", style="grey70"))
            return

        device, clients = details
        device_events = await self._store.get_device_events(self._device_id)
        self.query_one("#details-device", VerticalScroll).border_title = str(
            device["name"]
        )
        content.update(_device_details_text(device, clients, device_events))

    async def refresh_after_sync(self) -> None:
        """Refresh current details and plots after a poll."""
        await self._load_device_details()
        await self.refresh_plots()

    async def _initialize_plots(self) -> None:
        """Draw after the initial layout establishes the plot widths."""
        self._plots_ready = True
        await self.refresh_plots()

    async def refresh_plots(self, *, force: bool = False) -> None:
        """Refresh both rolling plots using the current plot dimensions."""
        await self.refresh_signal_plot(force=force)
        await self.refresh_usage_plot(force=force)

    async def refresh_signal_plot(self, *, force: bool = False) -> None:
        """Render the newest LTE samples at one Braille X-dot per sample."""
        plot = self.query_one("#signal-plot", _DateBoundedPlot)
        sample_limit = max(1, (plot.size.width - plot.margin_left) * 2)
        samples = await self._store.get_device_signal_samples(
            self._device_id, sample_limit
        )
        latest_sampled_at = str(samples[-1]["sampled_at"]) if samples else None
        if (
            not force
            and latest_sampled_at is not None
            and latest_sampled_at == self._signal_latest_sampled_at
        ):
            return

        viewport = plot.capture_x_viewport()

        plot.clear()
        plot.set_x_formatter(_LocalTimestampFormatter())
        plot.set_y_formatter(_SignalLevelFormatter())
        plot.set_yticks([0, 1, 2, 3])
        plot.set_ylimits(-0.25, 3.25)
        plot.set_ylabel("LTE Signal")
        if not samples:
            self._signal_latest_sampled_at = None
            return

        all_x_values = []
        points_by_level = {level: ([], []) for level in _SIGNAL_LEVELS}
        for sample in samples:
            sampled_at = datetime.fromisoformat(str(sample["sampled_at"]))
            if sampled_at.tzinfo is None:
                sampled_at = sampled_at.replace(tzinfo=timezone.utc)
            level = str(sample["lte_signal_level"])
            x_values, y_values = points_by_level[level]
            timestamp = sampled_at.timestamp()
            all_x_values.append(timestamp)
            x_values.append(timestamp)
            y_values.append(_SIGNAL_LEVELS[level])

        if len(all_x_values) == 1:
            plot.set_xlimits(all_x_values[0] - 30, all_x_values[0] + 30)
        else:
            plot.set_xlimits(all_x_values[0], all_x_values[-1])
        plot.set_sampled_at_bounds(all_x_values[0], all_x_values[-1])
        if viewport is not None:
            plot.restore_x_viewport(viewport)
        for level, (level_x_values, level_y_values) in points_by_level.items():
            if level_x_values:
                plot.scatter(
                    level_x_values,
                    level_y_values,
                    marker_style=_SIGNAL_STYLES[level],
                    hires_mode=HiResMode.BRAILLE,
                )
        self._signal_latest_sampled_at = latest_sampled_at

    async def refresh_usage_plot(self, *, force: bool = False) -> None:
        """Render log-scaled usage deltas at each later sample timestamp."""
        plot = self.query_one("#usage-plot", _DateBoundedPlot)
        point_capacity = max(1, (plot.size.width - plot.margin_left) * 2)
        samples = await self._store.get_device_usage_samples(
            self._device_id, point_capacity + 1
        )
        latest_sampled_at = str(samples[-1]["sampled_at"]) if samples else None
        if (
            not force
            and latest_sampled_at is not None
            and latest_sampled_at == self._usage_latest_sampled_at
        ):
            return

        viewport = plot.capture_x_viewport()

        plot.clear()
        plot.set_x_formatter(_LocalTimestampFormatter())
        plot.set_ylabel("Usage per Poll")
        if len(samples) < 2:
            self._configure_usage_axis(plot, 0)
            self._usage_latest_sampled_at = latest_sampled_at
            return

        x_values = []
        usage_deltas = []
        log_usage_values = []
        first_usage = samples[0]["cellular_data_usage_bytes"]
        if not isinstance(first_usage, int):
            self._configure_usage_axis(plot, 0)
            self._usage_latest_sampled_at = latest_sampled_at
            return
        previous_usage = first_usage
        for sample in samples[1:]:
            sampled_at = datetime.fromisoformat(str(sample["sampled_at"]))
            if sampled_at.tzinfo is None:
                sampled_at = sampled_at.replace(tzinfo=timezone.utc)
            current_usage = sample["cellular_data_usage_bytes"]
            if not isinstance(current_usage, int):
                continue
            usage_delta = current_usage - previous_usage
            previous_usage = current_usage
            if usage_delta < 0:
                continue
            x_values.append(sampled_at.timestamp())
            usage_deltas.append(usage_delta)
            log_usage_values.append(log10(usage_delta + 1))

        if not x_values:
            self._configure_usage_axis(plot, 0)
            self._usage_latest_sampled_at = latest_sampled_at
            return

        if len(x_values) == 1:
            plot.set_xlimits(x_values[0] - 30, x_values[0] + 30)
        else:
            plot.set_xlimits(x_values[0], x_values[-1])
        plot.set_sampled_at_bounds(x_values[0], x_values[-1])
        if viewport is not None:
            plot.restore_x_viewport(viewport)
        self._configure_usage_axis(plot, max(usage_deltas))
        plot.scatter(
            x_values,
            log_usage_values,
            marker_style="green1",
            hires_mode=HiResMode.BRAILLE,
        )
        self._usage_latest_sampled_at = latest_sampled_at

    @staticmethod
    def _configure_usage_axis(plot: _DateBoundedPlot, maximum_delta: int) -> None:
        tick_bytes = _usage_tick_bytes(maximum_delta)
        formatter = _UsageByteFormatter(tick_bytes)
        plot.set_y_formatter(formatter)
        plot.set_yticks(formatter.get_ticks(0, 0))
        plot.set_ylimits(-0.25, formatter.get_ticks(0, 0)[-1] + 0.25)

    def on_resize(self, _: events.Resize) -> None:
        if self._plots_ready:
            self.call_after_refresh(lambda: self.refresh_plots(force=True))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_ignore_quit(self) -> None:
        """Prevent quitting the application from the device detail screen."""


class UbiApp(App):
    """Monitoring dashboard for Ubiquiti UMR devices."""

    CSS = """
    #service-panel {
        height: 3;
        border: round $primary;
        padding: 0 1;
    }

    #service-status {
        width: 1fr;
        height: 100%;
        content-align: left middle;
    }

    #service-action {
        width: 21;
        min-width: 21;
        max-width: 21;
        height: 1;
        content-align: center middle;
        text-align: center;
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
    ]

    def __init__(self) -> None:
        super().__init__()
        self._systemd = SystemdService() if _SYSTEMD_AVAILABLE else None
        self._service_installed = (
            self._systemd is not None and self._systemd.is_installed()
        )
        self._can_manage_service = (
            self._systemd.can_manage() if self._systemd is not None else False
        )
        self._store = self._create_store()
        self._service_enabled = (
            "external"
            if _OBSERVER_MODE
            else "unknown"
            if self._service_installed
            else "not-found"
            if _SYSTEMD_AVAILABLE
            else "local"
        )
        self._service_active = "unknown" if self._service_installed else "inactive"
        self._local_api_client: MobilityApiClient | None = None
        self._local_monitor_service: MonitorService | None = None
        self._dashboard_refresh_interval_seconds = _dashboard_refresh_interval_seconds()
        self._device_table_signature: tuple[DeviceDashboardViewModel, ...] | None = None
        self._filter_text = ""
        self._filter_pattern: re.Pattern[str] | None = None

    def _create_store(self) -> SqliteSnapshotStore:
        """Create the database store appropriate for the current runtime mode."""
        if _OBSERVER_MODE:
            return SqliteSnapshotStore(configured_database_path(), read_only=True)
        if self._service_installed and self._systemd is not None:
            return SqliteSnapshotStore(
                configured_database_path(self._systemd.deployment_root),
                read_only=True,
            )
        if os.getenv("MONITORUBI_DATABASE_PATH"):
            return SqliteSnapshotStore(configured_database_path())
        return SqliteSnapshotStore(DEFAULT_DATABASE_PATH)

    def compose(self) -> ComposeResult:
        with Horizontal(id="service-panel") as service_panel:
            service_panel.border_title = "monitorUbi"
            yield Static(self.service_status_text(), id="service-status")
            if _SYSTEMD_AVAILABLE:
                yield Button(
                    "Install Service",
                    id="service-action",
                    variant="primary",
                    compact=True,
                )

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
        """Build the Rich status line from the current systemd state."""
        status_icon, status_label, status_style = self._service_status_display()
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
                self._service_enabled,
                "green1" if self._service_enabled == "enabled" else "yellow",
            ),
            (" | RAM Usage: ", "grey70"),
            (f"{memory_usage()}", "turquoise2"),
            (" | DB Size: ", "grey70"),
            (f"{database_size(self._store.database_path)}", "turquoise2"),
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
        service_action = "Stop" if self._monitor_running else "Start"
        entries: list[tuple[str, str]] = []
        if not _OBSERVER_MODE:
            entries.extend((("s", "bold cyan"), (f"={service_action}  ", "")))
        entries.extend(
            (
                ("q", "bold cyan"),
                ("=Quit  ", ""),
                ("f", "bold cyan"),
                ("=Filter  ", ""),
                ("Enter", "bold cyan"),
                ("=Details", ""),
            )
        )
        return Text.assemble(*entries)

    @property
    def _monitor_running(self) -> bool:
        """Whether the active local or system monitor is running."""
        if self._service_installed:
            return self._service_active == "active"
        return self._local_monitor_service is not None

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
        await self._refresh_dashboard()
        self.set_interval(
            self._dashboard_refresh_interval_seconds, self._refresh_dashboard
        )
        devices.focus()

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
        signature = tuple(filtered_view_models)
        if signature == self._device_table_signature:
            return

        selected_device_id = None
        if table.row_count:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            selected_device_id = row_key.value
        table.clear()
        for view_model in filtered_view_models:
            table.add_row(*view_model.table_row, key=view_model.device_id)
        self._device_table_signature = signature

        if selected_device_id is not None:
            for row_index, view_model in enumerate(filtered_view_models):
                if view_model.device_id == selected_device_id:
                    table.move_cursor(row=row_index)
                    break

    async def _refresh_dashboard(self) -> None:
        """Refresh persisted dashboard data and system service state."""
        try:
            await self._sync_installation_mode()
            if self._store.database_exists or not self._store.read_only:
                await self._store.refresh_current_counts()
                await self._store.refresh_history_days()
                await self.refresh_device_table()
                if isinstance(self.screen, DeviceDetailsScreen):
                    await self.screen.refresh_after_sync()
            else:
                self._device_table_signature = None
            await self._refresh_systemd_state()
        except Exception as error:
            self.notify(f"Dashboard refresh failed: {error}", severity="error")

    def action_toggle_service(self) -> None:
        if _OBSERVER_MODE:
            self.notify("Polling is managed by the external daemon.", severity="warning")
            return
        if self._service_installed and not self._can_manage_service:
            self.notify("Only the service owner can manage monitorUbi.", severity="warning")
            return

        action = "stop" if self._monitor_running else "start"
        prompt = (
            "Stop monitorUbi polling?"
            if action == "stop"
            else "Start monitorUbi polling?"
        )
        self.push_screen(
            ConfirmationScreen(prompt),
            lambda confirmed: self._after_start_stop_confirmation(confirmed, action),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "service-action":
            return
        if not self._can_manage_service:
            return
        action = self._service_button_action()
        if action is not None:
            self._request_privileged_action(action)

    def _after_start_stop_confirmation(self, confirmed: bool | None, action: str) -> None:
        """Run the confirmed keyboard action after the modal has closed."""
        if confirmed:
            if self._service_installed:
                self._request_privileged_action(action)
            else:
                self._request_local_action(action)

    @work(exclusive=True)
    async def _request_local_action(self, action: str) -> None:
        """Start or stop polling inside a non-installed TUI process."""
        if action == "start":
            await self._start_local_monitor()
        else:
            await self._stop_local_monitor()
        await self._refresh_systemd_state()

    async def _start_local_monitor(self) -> None:
        """Start local polling against the project-directory database."""
        if self._local_monitor_service is not None:
            return
        try:
            api_client = MobilityApiClient()
        except ValueError as error:
            self.notify(str(error), severity="error")
            return

        monitor_service = MonitorService(
            api_client,
            self._store,
            on_refresh=self._refresh_after_local_sync,
        )
        self._local_api_client = api_client
        self._local_monitor_service = monitor_service
        monitor_service.start()

    async def _stop_local_monitor(self) -> None:
        """Stop local polling and close its API client."""
        monitor_service = self._local_monitor_service
        api_client = self._local_api_client
        self._local_monitor_service = None
        self._local_api_client = None
        if monitor_service is not None:
            await monitor_service.stop()
        if api_client is not None:
            await api_client.aclose()

    async def _refresh_after_local_sync(self, _: SyncSummary) -> None:
        """Refresh immediately after an in-process poll completes."""
        await self._refresh_dashboard()

    @work(exclusive=True)
    async def _request_privileged_action(self, action: str) -> None:
        systemd = self._systemd
        if systemd is None:
            return
        password = await self.push_screen_wait(SudoPasswordScreen())
        if password is None:
            return

        completed = False
        try:
            await systemd.authenticate(password)
            match action:
                case "install":
                    await self._stop_local_monitor()
                    await systemd.install()
                case "enable":
                    await systemd.enable()
                case "uninstall":
                    await systemd.uninstall()
                case "start":
                    await systemd.start()
                case "stop":
                    await systemd.stop()
            completed = True
            self.notify(f"monitorUbi service {action} completed.")
        except SystemdError as error:
            self.notify(f"Service {action} failed: {error}", severity="error")
        finally:
            try:
                await systemd.clear_authentication()
            except SystemdError as error:
                self.notify(f"Could not clear sudo authentication: {error}", severity="error")
            await self._sync_installation_mode()
            await self._refresh_systemd_state()
            if completed and action in {"install", "uninstall"}:
                self.query_one("#device-table", DataTable).focus()

    async def _refresh_systemd_state(self) -> None:
        """Refresh local or systemd monitor state in the dashboard."""
        if _OBSERVER_MODE:
            self._service_enabled = "external"
            self._service_active = "unknown"
        elif self._service_installed and self._systemd is not None:
            status = await self._systemd.status()
            self._service_enabled = status.enabled
            self._service_active = status.active
        else:
            self._service_enabled = "not-found" if _IS_LINUX else "local"
            self._service_active = (
                "active" if self._local_monitor_service is not None else "inactive"
            )
        try:
            self.query_one("#service-status", Static).update(self.service_status_text())
            self.query_one("#footer-menu", Static).update(self.footer_text())
            if _SYSTEMD_AVAILABLE:
                button = self.query_one("#service-action", Button)
                action = self._service_button_action()
                button.label = (
                    self._service_button_label(action)
                    if self._can_manage_service
                    else "Observer Mode"
                )
                button.disabled = action is None or not self._can_manage_service
        except NoMatches:
            return

    async def _sync_installation_mode(self) -> None:
        """Switch database ownership mode when the Linux unit is added or removed."""
        systemd = self._systemd
        if systemd is None:
            return
        installed = systemd.is_installed()
        if installed == self._service_installed:
            return

        if installed:
            await self._stop_local_monitor()
        self._service_installed = installed
        self._can_manage_service = systemd.can_manage()
        self._store = self._create_store()
        self._device_table_signature = None
        self.query_one("#device-table", DataTable).clear()

    def _service_status_display(self) -> tuple[str, str, str]:
        """Map the active local or system service to dashboard vocabulary."""
        if _OBSERVER_MODE:
            return "?", "external", "yellow"
        if self._monitor_running:
            return "√", "running", "green1"
        if not self._service_installed or self._service_active == "inactive":
            return "X", "stopped", "red1"
        return "?", self._service_active, "yellow"

    def _service_button_action(self) -> str | None:
        """Return the requested management action for the enabled unit state."""
        if not self._service_installed:
            return "install"
        return {
            "disabled": "enable",
            "enabled": "uninstall",
        }.get(self._service_enabled)

    @staticmethod
    def _service_button_label(action: str | None) -> str:
        """Return the fixed-width button label for a systemd management action."""
        if action is None:
            return "Unavailable"
    
        return {
            "install": "Install Service",
            "enable": "Enable Service",
            "uninstall": "Uninstall Service",
        }.get(action, "Unavailable")

    async def on_unmount(self) -> None:
        await self._stop_local_monitor()

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
        self._device_table_signature = None
        await self.refresh_device_table()

    def action_details(self) -> None:
        table = self.query_one("#device-table", DataTable)
        if table.row_count == 0:
            self.notify("No device is selected.", severity="warning")
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value is not None:
            self.push_screen(DeviceDetailsScreen(self._store, row_key.value))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value is not None:
            self.push_screen(DeviceDetailsScreen(self._store, event.row_key.value))


def _device_details_text(
    device: dict[str, object], clients: list[dict[str, object]], events: list[str]
) -> Text:
    """Format current device and online-client data for the scrollable detail pane."""
    text = Text()
    for key in (
        "id",
        "model",
        "state",
        "firmware_version",
        "mac_address",
        "wan_source",
        "wan_ip",
        "enabled_wans",
        "isp",
        "lte_signal_level",
        "cellular_data_usage_bytes",
        "cellular_data_limit_bytes",
        "memory_usage_percent",
        "client_count",
        "host_address",
        "poe_passthrough",
        "device_mode",
        "wifi_enabled",
        "wifi_ssid",
        "tx_power_level",
        "vpn_profile_name",
        "vpn_status",
        "firewall_rule_names",
        "routing_rule_names",
        "ddns_profile_names",
        "subscription_plan",
        "subscription_status",
    ):
        _append_detail_row(text, key, device[key])

    uptime_seconds = device["uptime_seconds"]
    if isinstance(uptime_seconds, int):
        _append_detail_row(
            text, "uptime", f"{uptime_seconds} ({uptime_seconds_to_string(uptime_seconds)})"
        )

    latitude = device["latitude"]
    longitude = device["longitude"]
    if latitude is None and longitude is None:
        _append_detail_row(text, "location", None)
    else:
        text.append("location:\n", style=_DETAIL_LABEL_STYLE)
        text.append("  {\n", style=_DETAIL_LABEL_STYLE)
        text.append('    "latitude": ', style=_DETAIL_LABEL_STYLE)
        text.append("-" if latitude is None else str(latitude), style=_DETAIL_VALUE_STYLE)
        text.append(",\n", style=_DETAIL_LABEL_STYLE)
        text.append('    "longitude": ', style=_DETAIL_LABEL_STYLE)
        text.append("-" if longitude is None else str(longitude), style=_DETAIL_VALUE_STYLE)
        text.append("\n  }\n", style=_DETAIL_LABEL_STYLE)

    text.append("\nClients\n", style="bold")
    if not clients:
        text.append("None\n", style="turquoise2")
    else:
        for index, client in enumerate(clients):
            for key in ("mac", "name", "type", "connection_status", "ip_address", "is_blocked"):
                _append_detail_row(text, key, client[key])
            if index < len(clients) - 1:
                text.append("\n")

    text.append("\nEvents\n", style="bold")
    if not events:
        text.append("None\n", style=_DETAIL_VALUE_STYLE)
        return text

    for event in events:
        text.append(f"{event}\n", style=_DETAIL_VALUE_STYLE)
    return text


def _append_detail_row(text: Text, key: str, value: object) -> None:
    """Append a styled detail label and value."""
    text.append(f"{key}: ", style=_DETAIL_LABEL_STYLE)
    text.append("-" if value is None else str(value), style=_DETAIL_VALUE_STYLE)
    text.append("\n")
