import psutil
import os

def memory_usage() -> str:
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    if mem_info.rss >= 1024**3: 
        return f"{mem_info.rss / 1024**3:5.1f} GB"
    elif mem_info.rss >= 1024**2:
        return f"{mem_info.rss / 1024**2:5.1f} MB"
    return f"{mem_info.rss / 1024:5.1f} KB"

def uptime_seconds_to_string(uptime_seconds: int) -> str:
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(days)}d:{int(hours)}h:{int(minutes)}m:{int(seconds)}s"


if __name__ == "__main__":
    def example():
        print(f"Memory usage: {memory_usage()}")
        print(f"Uptime: {uptime_seconds_to_string(2289321)}")
    
    example()
