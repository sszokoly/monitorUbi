"""SNMP v2c trap delivery for monitorUbi device transitions."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from loguru import logger
from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    NotificationType,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    send_notification,
)
from pysnmp.proto.rfc1902 import OctetString

from monitorUbi.config import get_setting, load_config


def _configured_trap_targets() -> list[tuple[str, int, str]]:
    """Return TOML SNMP targets, with no targets when configuration is absent."""
    config, _ = load_config()
    targets = get_setting(config, "snmp", "trap_targets", [])
    if not isinstance(targets, list):
        raise ValueError("Configuration snmp.trap_targets must be an array")

    parsed_targets = []
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("Each SNMP trap target must be a table")
        try:
            parsed_targets.append(
                (str(target["host"]), int(target["port"]), str(target["community"]))
            )
        except KeyError as error:
            raise ValueError("Each SNMP trap target needs host, port, and community") from error
    return parsed_targets

ENTERPRISE_OID = "1.3.6.1.4.1.8247884.1"


class TrapEvent(str, Enum):
    """Device transition events represented by monitorUbi traps."""

    DEVICE_DISCONNECTED = "deviceDisconnected"
    DEVICE_CONNECTED = "deviceConnected"
    CLIENTS_OFFLINE = "clientsOffline"
    CLIENTS_ONLINE = "clientsOnline"


_EVENT_OIDS = {
    TrapEvent.DEVICE_DISCONNECTED: f"{ENTERPRISE_OID}.0.1",
    TrapEvent.DEVICE_CONNECTED: f"{ENTERPRISE_OID}.0.2",
    TrapEvent.CLIENTS_OFFLINE: f"{ENTERPRISE_OID}.0.3",
    TrapEvent.CLIENTS_ONLINE: f"{ENTERPRISE_OID}.0.4",
}

_MESSAGE_OID = f"{ENTERPRISE_OID}.1.1"


@dataclass(frozen=True)
class DeviceTrap:
    """A concise device-transition notification."""

    event: TrapEvent
    device_id: UUID
    device_name: str
    observed_at: datetime

    @property
    def message(self) -> str:
        """Return the human-readable message delivered in the trap varbind."""
        timestamp = self.observed_at.astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
        match self.event:
            case TrapEvent.DEVICE_DISCONNECTED:
                event_text = "DISCONNECTED"
            case TrapEvent.DEVICE_CONNECTED:
                event_text = "CONNECTED"
            case TrapEvent.CLIENTS_OFFLINE:
                event_text = "clients OFFLINE"
            case TrapEvent.CLIENTS_ONLINE:
                event_text = "clients ONLINE"
        return f"Device {self.device_name} {event_text} at {timestamp}"


class SnmpTrapSender:
    """Send monitorUbi device traps to each configured SNMP v2c target."""

    def __init__(self, targets: list[tuple[str, int, str]] | None = None) -> None:
        self._targets = _configured_trap_targets() if targets is None else targets

    async def send(self, trap: DeviceTrap) -> None:
        """Send a trap to every target without propagating delivery failures."""
        if not self._targets:
            return

        await asyncio.gather(
            *(self._send_target(target, trap) for target in self._targets),
            return_exceptions=True,
        )

    async def _send_target(
        self, target: tuple[str, int, str], trap: DeviceTrap
    ) -> None:
        host, port, community = target
        try:
            error_indication, error_status, error_index, _ = await send_notification(
                SnmpEngine(),
                CommunityData(community, mpModel=1),
                await UdpTransportTarget.create((host, port)),
                ContextData(),
                "trap",
                NotificationType(ObjectIdentity(_EVENT_OIDS[trap.event])).add_varbinds(
                    ObjectType(ObjectIdentity(_MESSAGE_OID), OctetString(trap.message))
                ),
            )
            if error_indication:
                raise RuntimeError(str(error_indication))
            if error_status:
                raise RuntimeError(
                    f"{error_status.prettyPrint()} at varbind {error_index}"
                )
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to send SNMP trap {event} for device {device_name} to {host}:{port}",
                event=trap.event.value,
                device_name=trap.device_name,
                host=host,
                port=port,
            )
        else:
            logger.info(
                "Sent SNMP trap {event} for device {device_name} to {host}:{port}",
                event=trap.event.value,
                device_name=trap.device_name,
                host=host,
                port=port,
            )


if __name__ == "__main__":
    async def main() -> None:
        trap = DeviceTrap(
            event=TrapEvent.DEVICE_CONNECTED,
            device_id=UUID("00000000-0000-0000-0000-000000000000"),
            device_name="TestDevice",
            observed_at=datetime.now(timezone.utc),
        )
        sender = SnmpTrapSender()
        await sender.send(trap)

    asyncio.run(main())
