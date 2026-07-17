import psutil
import os

def memory_usage():
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    rss_mb = mem_info.rss / 1024 / 1024
    return f"{rss_mb:.2f}"
