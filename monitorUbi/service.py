# service.py
import asyncio
import logging
import signal
from typing import Callable, Optional
import client
import db

logger = logging.getLogger(__name__)

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
    asyncio.run(run_headless_daemon())
