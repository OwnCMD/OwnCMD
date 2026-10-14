"""Read-only host metrics. Invoked only inside the protected Docker broker."""

import os, shutil, time
from pathlib import Path


def cpu_ticks():
    values = [
        int(n) for n in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]
    ]
    return sum(values), values[3] + values[4]


def cpu_percent(before, after):
    total = after[0] - before[0]
    idle = after[1] - before[1]
    return (
        round(max(0, min(100, 100 * (total - idle) / total)), 2) if total > 0 else None
    )


def host_snapshot(data_path):
    result = {
        "checked_at": time.time(),
        "cpu_count": os.cpu_count(),
        "memory": None,
        "disk": None,
        "uptime_seconds": None,
        "load": None,
    }
    try:
        mem = {
            line.split(":")[0]: int(line.split()[1]) * 1024
            for line in Path("/proc/meminfo").read_text().splitlines()
            if len(line.split()) >= 2
        }
        total = mem["MemTotal"]
        available = mem.get("MemAvailable", mem.get("MemFree", 0))
        used = max(0, total - available)
        result["memory"] = {
            "total": total,
            "used": used,
            "available": available,
            "percent": round(used / total * 100, 2) if total else None,
        }
    except (OSError, ValueError, KeyError):
        pass
    try:
        disk = shutil.disk_usage(data_path)
        result["disk"] = {
            "total": disk.total,
            "used": disk.used,
            "available": disk.free,
            "percent": round(disk.used / disk.total * 100, 2) if disk.total else None,
        }
    except OSError:
        pass
    try:
        result["uptime_seconds"] = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    try:
        result["load"] = list(os.getloadavg())
    except OSError:
        pass
    return result
