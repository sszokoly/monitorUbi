# service.py
import asyncio
import logging
import signal
from typing import Callable, Optional
from db import upsert_workspaces
from schemas import WorkspaceCollectionResponse
from client import request_workspaces, request_devices

logger = logging.getLogger(__name__)

WORKSPACES_FETCH_FREQ_SECS = 180
DEVICES_FETCH_FREQ_SECS = 180



async def workspaces_from_web(pause_time=WORKSPACES_FETCH_FREQ_SECS):
    try:
        content = await request_workspaces()
        if content is None:
            return
        resp = WorkspaceCollectionResponse.model_validate_json(content)
        if resp.data and not resp.err:
            await upsert_workspaces(resp.data)
        return [ws.model_dump(mode="json")["workspace_id"] for ws in resp.data]
    except:
        return []


async def fetch_devices(pause_time=WORKSPACES_FETCH_FREQ_SECS):
    try:
        wp_ids = await fetch_workspaces()
        if not wp_ids:
            return
        
        tasks = [request_devices(wp_id) for wp_id in wp_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
    except:
        return []



class DeviceMonitorService:
    def __init__(self, on_refresh_callback: Optional[Callable[[], None]] = None):
        self.on_refresh = on_refresh_callback
        self._monitor_task: Optional[asyncio.Task] = None
        self.is_running = False

    def start(self) -> None:
        """Starts the asynchronous monitoring loop."""
        if not self.is_running:
            self.is_running = True
            self._monitor_task = asyncio.create_task(self._run_loop())
            logger.info("Device Monitor Service started.")

    async def stop(self) -> None:
        """Gracefully cancels the background loop for clean shutdown."""
        if self.is_running and self._monitor_task:
            self.is_running = False
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass  # Safe, expected exit path
            logger.info("Device Monitor Service stopped cleanly.")

    async def _run_loop(self) -> None:
        """Continuous pipeline: REST Fetch -> DB Upsert -> UI Trigger."""
        while self.is_running:
            try:
                device_data = await client.fetch_device_status()
                await db.upsert_device_metrics(device_data)
                
                # If running in TUI mode, notify the UI to refresh
                if self.on_refresh:
                    self.on_refresh()
                    
            except Exception as e:
                logger.error(f"Error in service sync loop: {e}")
                
            await asyncio.sleep(5)

# -------------------------------------------------------------------------
# SYSTEMD INTEGRATION ENTRY POINT
# This executes ONLY when running headless as a background Linux service
# -------------------------------------------------------------------------
async def run_headless_daemon():
    """Wrapper to run the service stand-alone with OS signal handling."""
    logging.basicConfig(level=logging.INFO)
    
    # Initialize connection pools on startup
    await db.initialize_database() 
    
    service = DeviceMonitorService()
    service.start()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    # Register OS termination hooks required by systemctl stop
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    # Keep alive until systemd triggers the stop event
    await stop_event.wait()
    
    # Clean up tasks and close connection pools gracefully
    await service.stop()
    await db.close_database()

if __name__ == "__main__":
    # Running this file directly fires up the headless Linux daemon mode
    #asyncio.run(run_headless_daemon())
    ws = asyncio.run(fetch_devices())
    print(ws)