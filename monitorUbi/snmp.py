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


SNMP_TRAP_TARGETS: list[tuple[str, int, str]] = []
"""SNMP v2c targets as ``(host, port, community)`` tuples."""

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

_DEVICE_ID_OID = f"{ENTERPRISE_OID}.1.1"
_DEVICE_NAME_OID = f"{ENTERPRISE_OID}.1.2"
_WORKSPACE_ID_OID = f"{ENTERPRISE_OID}.1.3"
_PREVIOUS_VALUE_OID = f"{ENTERPRISE_OID}.1.4"
_CURRENT_VALUE_OID = f"{ENTERPRISE_OID}.1.5"
_OBSERVED_AT_OID = f"{ENTERPRISE_OID}.1.6"


@dataclass(frozen=True)
class DeviceTrap:
    """Details included with one device transition notification."""

    event: TrapEvent
    workspace_id: UUID
    device_id: UUID
    device_name: str
    previous_value: str
    current_value: str
    observed_at: datetime


class SnmpTrapSender:
    """Send monitorUbi device traps to each configured SNMP v2c target."""

    def __init__(self, targets: list[tuple[str, int, str]] | None = None) -> None:
        self._targets = SNMP_TRAP_TARGETS if targets is None else targets

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
                    ObjectType(
                        ObjectIdentity(_DEVICE_ID_OID), OctetString(str(trap.device_id))
                    ),
                    ObjectType(
                        ObjectIdentity(_DEVICE_NAME_OID), OctetString(trap.device_name)
                    ),
                    ObjectType(
                        ObjectIdentity(_WORKSPACE_ID_OID),
                        OctetString(str(trap.workspace_id)),
                    ),
                    ObjectType(
                        ObjectIdentity(_PREVIOUS_VALUE_OID),
                        OctetString(trap.previous_value),
                    ),
                    ObjectType(
                        ObjectIdentity(_CURRENT_VALUE_OID),
                        OctetString(trap.current_value),
                    ),
                    ObjectType(
                        ObjectIdentity(_OBSERVED_AT_OID),
                        OctetString(
                            trap.observed_at.astimezone(timezone.utc).isoformat()
                        ),
                    ),
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
                "Failed to send SNMP trap {event} for device {device_id} to {host}:{port}",
                event=trap.event.value,
                device_id=trap.device_id,
                host=host,
                port=port,
            )
        else:
            logger.info(
                "Sent SNMP trap {event} for device {device_id} to {host}:{port}",
                event=trap.event.value,
                device_id=trap.device_id,
                host=host,
                port=port,
            )
