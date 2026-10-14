"""Machine details recorded with every benchmark result (benchmark numbers are meaningless without them)."""
from __future__ import annotations

import os
import platform
import sys
from datetime import datetime
from pathlib import Path


def peak_memory_mb() -> float | None:
    """Peak resident memory of THIS process in MB, or None if unavailable. (Windows branch is untested.)"""
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)
    except ImportError:
        pass
    try:  # Windows
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(c), c.cb):
            return round(c.PeakWorkingSetSize / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        pass
    return None


def total_ram_gb() -> float | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / (1024 * 1024), 1)
    except OSError:
        pass
    try:  # Windows (untested)
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
        s = Status()
        s.dwLength = ctypes.sizeof(s)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
            return round(s.ullTotalPhys / (1024 ** 3), 1)
    except Exception:  # noqa: BLE001
        pass
    return None


def git_commit(root: Path) -> str | None:
    from code_analyzer.scanner import read_git_info
    info = read_git_info(root)
    return (info or {}).get("commit")


def machine_info(root: Path | None = None) -> dict:
    from config import TOOL_VERSION
    root = root or Path(__file__).resolve().parent.parent
    return {"timestamp": datetime.now().isoformat(timespec="seconds"), "tool_version": TOOL_VERSION,
            "os": f"{platform.system()} {platform.release()}", "machine": platform.machine(), "processor": platform.processor() or "unknown",
            "cpu_count": os.cpu_count(), "ram_gb": total_ram_gb(), "python": platform.python_version(),
            "python_implementation": platform.python_implementation(), "git_commit": git_commit(root)}
