from uuid import UUID
from typing import Optional, List
from pydantic import BaseModel, Field, IPvAnyAddress, field_validator


class Workspace(BaseModel):
    """Model representing a workspace."""
    workspace_id: UUID
    workspace_name: str = Field(min_length=1, max_length=255)
    is_owner: bool
    status: str = Field(pattern=r"^[A-Z_]+$")

class WorkspaceCollectionResponse(BaseModel):
    """Model matching the Ubiquiti API's top-level JSON structure."""
    err: Optional[str] = None
    type: str = Field(pattern=r"^collection$")  
    data: List[Workspace]
    trace_id: str
    offset: int
    limit: int
    total: int

class DeviceSummary(BaseModel):
    """Model representing the lighter device data returned in lists."""
    id: UUID
    name: str = Field(min_length=1, max_length=255)
    model: str
    state: str = Field(pattern=r"^[A-Z_]+$")
    firmware_version: str
    mac_address: str = Field(pattern=r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$")

class DeviceCollectionResponse(BaseModel):
    """Model matching the collection-level response API envelope."""
    err: Optional[str] = None
    type: str = Field(pattern=r"^collection$")
    data: List[DeviceSummary]
    offset: int = Field(ge=0)
    limit: int = Field(ge=0)
    total: int = Field(ge=0)

class DeviceLocation(BaseModel):
    """Model matching the nested location dictionary."""
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    last_updated: int  # Epoch timestamp in milliseconds

class Device(BaseModel):
    """Model representing the detailed device attributes."""
    id: UUID
    name: str = Field(min_length=1, max_length=255)
    model: str
    state: str = Field(pattern=r"^[A-Z_]+$")
    firmware_version: str
    mac_address: str = Field(pattern=r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$")
    wan_source: str
    wan_ip: Optional[IPvAnyAddress] = None
    enabled_wans: List[str]
    isp: Optional[str] = None
    lte_signal_level: Optional[str] = None
    cellular_data_usage_bytes: int = Field(ge=0)
    cellular_data_limit_bytes: int = Field(ge=-1)
    memory_usage_percent: int = Field(ge=0, le=100)
    uptime_seconds: int = Field(ge=0)
    client_count: int = Field(ge=0)
    host_address: IPvAnyAddress
    poe_passthrough: bool
    device_mode: str
    wifi_enabled: bool
    wifi_ssid: Optional[str] = ""
    tx_power_level: Optional[str] = ""
    vpn_profile_name: Optional[str] = ""
    vpn_status: Optional[str] = ""
    firewall_rule_names: List[str]
    routing_rule_names: List[str]
    ddns_profile_names: List[str]
    subscription_plan: str
    subscription_status: str
    location: Optional[DeviceLocation] = None

class DeviceResponse(BaseModel):
    """Model matching the API's top-level JSON envelope."""
    err: Optional[str] = None
    type: str = Field(pattern=r"^single$")
    data: Device

class DeviceClient(BaseModel):
    """Model representing an individual client machine or user device."""
    mac: str = Field(pattern=r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$")
    name: Optional[str] = ""
    type: str = Field(pattern=r"^(WIRED|WIRELESS)$")
    connection_status: str = Field(pattern=r"^(ONLINE|OFFLINE)$")
    ip_address: Optional[IPvAnyAddress] = None
    is_blocked: bool
    # Optional field that only appears on WIRELESS clients (0 to 100%)
    wifi_experience: Optional[int] = Field(default=None, ge=0, le=100)

    @field_validator("ip_address", mode="before")
    @classmethod
    def empty_str_to_none(cls, value):
        """Converts empty string IP addresses to None so validation passes."""
        if value == "":
            return None
        return value

class ClientCollectionResponse(BaseModel):
    """Model matching the client collection API response envelope."""
    err: Optional[str] = None
    type: str = Field(pattern=r"^collection$")
    data: List[DeviceClient]
    offset: int = Field(ge=0)
    limit: int = Field(ge=0)
    total: int = Field(ge=0)


if __name__ == "__main__":
    workspaces_response = '''{
        "err": null,
        "type": "collection",
        "data": [
            {
                "workspace_id": "019c0d0f-2018-7677-bfbf-6594c5546369",
                "workspace_name": "Test Cloud 1",
                "is_owner": true,
                "status": "ACTIVE"
            },
            {
                "workspace_id": "019ed77e-9ebb-730d-8080-5362aaab8830",
                "workspace_name": "Test Cloud 2",
                "is_owner": false,
                "status": "ACTIVE"
            },
            {
                "workspace_id": "019c0637-f0ff-7ba6-8585-62e14a2ebdb1",
                "workspace_name": "Test Cloud 3",
                "is_owner": false,
                "status": "ACTIVE"
            }
        ],
        "trace_id": "2136bb248de6e7f7a73f9df7c3f9a907",
        "offset": 0,
        "limit": 0,
        "total": 3
    }'''

    validated_response = WorkspaceCollectionResponse.model_validate_json(workspaces_response)
    print("#### Validated Workspace Collection Response ####")
    print(validated_response, "\n\n")

    devices_response_collection = '''{
        "err": null,
        "type": "collection",
        "data": [
            {
                "id": "019edbe2-248c-74ff-8000-beeced92aeee",
                "name": "UMR1",
                "model": "UMR Industrial",
                "state": "CONNECTED",
                "firmware_version": "1.17.11",
                "mac_address": "12:34:56:78:90:12"
            },
            {
                "id": "019bd81c-f4d5-7a2b-b2b2-26228433deee",
                "name": "UMR2",
                "model": "UMR Industrial",
                "state": "DISCONNECTED",
                "firmware_version": "1.17.11",
                "mac_address": "01:02:03:04:05:06"
            }
        ],
        "offset": 0,
        "limit": 200,
        "total": 2
        }'''
    
    validated_response = DeviceCollectionResponse.model_validate_json(devices_response_collection)
    print("#### Validated Device Collection Response ####")
    print(validated_response, "\n\n")

    device_response_single = '''{ 
        "err": null,
        "type": "single",
        "data": 
            { 
                "id": "019edbe2-248c-74ff-80ea-beeced92acec",
                "name": "UMR1",
                "model": "UMR Industrial",
                "state": "CONNECTED",
                "firmware_version": "1.17.11",
                "mac_address": "12:34:56:78:90:12",
                "wan_source": "WAN",
                "wan_ip": "192.168.78.5",
                "enabled_wans": [ "WAN", "LTE" ],
                "isp": "Bell",
                "lte_signal_level": "STRONG",
                "cellular_data_usage_bytes": 565924,
                "cellular_data_limit_bytes": -1,
                "memory_usage_percent": 40,
                "uptime_seconds": 77779,
                "client_count": 1,
                "host_address": "192.168.105.1",
                "poe_passthrough": false,
                "device_mode": "ROUTER",
                "wifi_enabled": true,
                "wifi_ssid": "UMR1",
                "tx_power_level": "HIGH",
                "vpn_profile_name": "",
                "vpn_status": "",
                "firewall_rule_names": [],
                "routing_rule_names": [],
                "ddns_profile_names": [],
                "subscription_plan": "CLOUD",
                "subscription_status": "ACTIVE",
                "location": {
                    "latitude": 50.00000,
                    "longitude": -113.00000,
                    "last_updated": 1781873575628
                }
            }
        }'''
    
    validated_response = DeviceResponse.model_validate_json(device_response_single)
    print("#### Validated Device Response ####")
    print(validated_response, "\n\n")

    device_clients_response_collection = '''{
        "err": null,
        "type": "collection",
        "data": [
            {
                "mac": "ec:74:d7:ec:ec:ec",
                "name": "",
                "type": "WIRED",
                "connection_status": "ONLINE",
                "ip_address": "192.168.105.54",
                "is_blocked": false
            },
            {
                "mac": "d4:e9:8a:d4:d4:d4",
                "name": "pc1",
                "type": "WIRELESS",
                "connection_status": "OFFLINE",
                "ip_address": "",
                "is_blocked": false,
                "wifi_experience": 100
            },
            {
                "mac": "8c:b8:7e:0a:0a:0a",
                "name": "pc2",
                "type": "WIRELESS",
                "connection_status": "OFFLINE",
                "ip_address": "",
                "is_blocked": false,
                "wifi_experience": 45
            }
        ],
        "offset": 0,
        "limit": 200,
        "total": 3
        }'''
    validated_response = ClientCollectionResponse.model_validate_json(device_clients_response_collection)
    print("#### Validated Device Clients Collection Response ####")
    print(validated_response, "\n\n")
