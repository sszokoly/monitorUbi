import psutil
import os

def memory_usage():
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    if mem_info.rss >= 1024**3: 
        return f"{mem_info.rss / 1024**3:5.1f} GB"
    elif mem_info.rss >= 1024**2:
        return f"{mem_info.rss / 1024**2:5.1f} MB"
    return f"{mem_info.rss / 1024:5.1f} KB"


if __name__ == "__main__":
    print(f"Memory usage: {memory_usage()}")