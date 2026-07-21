import asyncio
import httpx2
import os
from dotenv import load_dotenv

load_dotenv()

UBI_API_KEY: str | None = os.getenv("UBI_API_KEY")

async def make_request(url, params=None, timeout=5.0):
    headers = {
        "Accept" : "application/json",
        "X-API-Key": UBI_API_KEY
    }
    
    if isinstance(params, dict):
        params = {k: v for k, v in params.items() if v is not None}
        if not params:
            params = None
            
    async with httpx2.AsyncClient(headers=headers) as client:
        try:
            response = await client.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response, None
            
        except httpx2.TimeoutException as err:
            return None, err
            
        except httpx2.HTTPStatusError as err:
            return None, err
            
        except httpx2.RequestError as err:
            return None, err

async def request_workspaces(timeout=5.0):
    url = "https://api.ui.com/v1/mobility/workspaces"
    response, err = await make_request(url, timeout=timeout)
    if err:
        print(f"Request error: {err}")
    return response.content if response else None

async def request_devices(workspace_id, timeout=5.0, limit=None, offset=None):
    url = f"https://api.ui.com/v1/mobility/workspaces/{workspace_id}/devices"
    
    query_params = {}
    if limit is not None:
        query_params["limit"] = limit
    if offset is not None:
        query_params["offset"] = offset
    
    response, err = await make_request(
        url, params=query_params, timeout=timeout
    )
    if err:
        print(f"Request error: {err}")
    return response.content if response else None


async def request_device_clients(workspace_id, device_id, timeout=5.0, limit=None, offset=None):
    url = f"https://api.ui.com/v1/mobility/workspaces/{workspace_id}/devices/{device_id}/clients?limit={limit}&offset={offset}"
    
    query_params = {}
    if limit is not None:
        query_params["limit"] = limit
    if offset is not None:
        query_params["offset"] = offset
    
    response, err = await make_request(
        url, params=query_params, timeout=timeout
    )
    if err:
        print(f"Request error: {err}")
    return response.content if response else None


async def request_device_details(workspace_id, device_id, timeout=5.0):
    url = f"https://api.ui.com/v1/mobility/workspaces/{workspace_id}/devices/{device_id}"
    response, err = await make_request(url, timeout=timeout)
    if err:
        print(f"Request error: {err}")
    return response.content if response else None


if __name__ == "__main__":
    import time

    async def main():
        workspace_id = os.getenv("WORKSPACE_ID")
        device_id = os.getenv("DEVICE_ID")
        results = await asyncio.gather(
            request_workspaces(),
            #request_devices(workspace_id=workspace_id),
            #request_device_details(workspace_id=workspace_id, device_id=device_id),
            #request_device_clients(workspace_id=workspace_id, device_id=device_id),
            #return_exceptions=True
        )

        for response in results:
            print("==========")
            print(response)

    asyncio.run(main())
