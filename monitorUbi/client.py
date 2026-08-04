"""Typed HTTP gateway for the UniFi Mobility API."""

import os
from typing import Optional
from uuid import UUID

import httpx2
from dotenv import load_dotenv
from loguru import logger

from monitorUbi.config import get_setting, load_config
from monitorUbi.schemas import (
    ClientCollectionResponse,
    Device,
    DeviceClient,
    DeviceCollectionResponse,
    DeviceResponse,
    DeviceSummary,
    Workspace,
    WorkspaceCollectionResponse,
)


load_dotenv()

API_BASE_URL = "https://api.ui.com"
MOBILITY_API_PREFIX = "/v1/mobility"
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_PAGE_SIZE = 200


class MobilityApiError(RuntimeError):
    """A transport or API-envelope error returned by the Mobility API."""

    def __init__(self, endpoint: str, message: str, trace_id: Optional[str] = None):
        self.endpoint = endpoint
        self.trace_id = trace_id
        detail = f"{endpoint}: {message}"
        if trace_id:
            detail = f"{detail} (trace_id={trace_id})"
        super().__init__(detail)


class MobilityApiClient:
    """Fetch and validate Mobility API resources as Pydantic models."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float | None = None,
        http_client: Optional[httpx2.AsyncClient] = None,
    ) -> None:
        self._owns_http_client = http_client is None
        if timeout is None:
            config, _ = load_config()
            timeout = float(
                get_setting(
                    config, "client", "default_timeout_seconds", DEFAULT_TIMEOUT_SECONDS
                )
            )

        if http_client is not None:
            self._http_client = http_client
            return

        api_key = api_key or os.getenv("UBI_API_KEY")
        if not api_key:
            raise ValueError("UBI_API_KEY must be configured")

        self._http_client = httpx2.AsyncClient(
            base_url=API_BASE_URL,
            headers={
                "Accept": "application/json",
                "X-API-Key": api_key,
            },
            timeout=timeout,
        )

    async def __aenter__(self) -> "MobilityApiClient":
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the internally created HTTP connection pool."""
        if self._owns_http_client:
            await self._http_client.aclose()

    async def list_workspaces(self) -> list[Workspace]:
        """Return every workspace visible to the API key."""
        endpoint = f"{MOBILITY_API_PREFIX}/workspaces"
        response = WorkspaceCollectionResponse.model_validate_json(
            await self._get_content(endpoint)
        )
        self._raise_for_api_error(endpoint, response.err, response.trace_id)
        return response.data

    async def list_devices(self, workspace_id: UUID) -> list[DeviceSummary]:
        """Return all device summaries in a workspace."""
        endpoint = f"{MOBILITY_API_PREFIX}/workspaces/{workspace_id}/devices"
        devices: list[DeviceSummary] = []
        offset = 0

        while True:
            response = DeviceCollectionResponse.model_validate_json(
                await self._get_content(
                    endpoint,
                    params={"limit": MAX_PAGE_SIZE, "offset": offset},
                )
            )
            self._raise_for_api_error(endpoint, response.err, response.trace_id)
            devices.extend(response.data)

            if not response.data or offset + len(response.data) >= response.total:
                return devices
            offset += len(response.data)

    async def get_device(self, workspace_id: UUID, device_id: UUID) -> Device:
        """Return detailed monitoring data for one device."""
        endpoint = (
            f"{MOBILITY_API_PREFIX}/workspaces/{workspace_id}/devices/{device_id}"
        )
        response = DeviceResponse.model_validate_json(await self._get_content(endpoint))
        self._raise_for_api_error(endpoint, response.err, response.trace_id)
        return response.data

    async def list_device_clients(
        self, workspace_id: UUID, device_id: UUID
    ) -> list[DeviceClient]:
        """Return all clients associated with one device."""
        endpoint = (
            f"{MOBILITY_API_PREFIX}/workspaces/{workspace_id}"
            f"/devices/{device_id}/clients"
        )
        clients: list[DeviceClient] = []
        offset = 0

        while True:
            response = ClientCollectionResponse.model_validate_json(
                await self._get_content(
                    endpoint,
                    params={"limit": MAX_PAGE_SIZE, "offset": offset},
                )
            )
            self._raise_for_api_error(endpoint, response.err, response.trace_id)
            clients.extend(response.data)

            if not response.data or offset + len(response.data) >= response.total:
                return clients
            offset += len(response.data)

    async def _get_content(
        self, endpoint: str, params: Optional[dict[str, int]] = None
    ) -> bytes:
        """Fetch one endpoint and return its body for Pydantic validation."""
        logger.debug("GET {endpoint} params={params}", endpoint=endpoint, params=params)
        try:
            response = await self._http_client.get(endpoint, params=params)
            response.raise_for_status()
        except httpx2.HTTPError as error:
            logger.opt(exception=error).debug("GET {endpoint} failed", endpoint=endpoint)
            raise MobilityApiError(endpoint, str(error)) from error
        logger.debug(
            "GET {endpoint} -> {status_code}",
            endpoint=endpoint,
            status_code=response.status_code,
        )
        return response.content

    @staticmethod
    def _raise_for_api_error(
        endpoint: str, error: Optional[str], trace_id: Optional[str]
    ) -> None:
        if error:
            logger.debug(
                "API error from {endpoint}: {error} trace_id={trace_id}",
                endpoint=endpoint,
                error=error,
                trace_id=trace_id,
            )
            raise MobilityApiError(endpoint, error, trace_id)


if __name__ == "__main__":
    import asyncio
    from monitorUbi.logging_setup import configure_logging
    
    configure_logging(mode="headless")

    async def example():
        client = MobilityApiClient()
        workspaces = await client.list_workspaces()
        print("=== WORKSPACES === \n", workspaces, "\n")
        
        devices = await client.list_devices(workspaces[2].workspace_id)
        print("=== DEVICES === \n", devices, "\n")
        
        clients = await client.list_device_clients(
            workspaces[2].workspace_id,
            devices[0].id
        )
        print(f"=== DEVICE {devices[0].id} CLIENTS === \n", clients, "\n")

    asyncio.run(example())
