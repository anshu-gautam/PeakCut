"""How busy the server really is, measured every second: processor, memory and disk.

Nothing here counts people. New heavy work (another video, another recording) starts only while the machine has
room, waits in line for a moment when it is nearly full, and is let through the second it frees up again. That is
what keeps a rush from slowing everyone down or crashing the server."""
import os
import shutil
import sys
import threading
import time

from . import config

BUSY_CPU = float(config.env("PEAKCUT_BUSY_CPU", "82"))          # percent: above this, no extra videos are started
MIN_FREE_RAM_GB = float(config.env("PEAKCUT_MIN_FREE_RAM_GB", "1.5"))
MIN_FREE_DISK_GB = float(config.env("PEAKCUT_MIN_FREE_DISK_GB", "3"))

_state = {"cpu": 0.0, "ram_free": 99.0, "disk_free": 99.0, "at": 0.0}
_force = None            # tests only: pretend the server is busy (True) or free (False)
_started = False
_lock = threading.Lock()


def _cpu_times():
    """(busy, total) processor time so far, in any unit."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        n = lambda f: (f.dwHighDateTime << 32) | f.dwLowDateTime          # noqa: E731
        total = n(kernel) + n(user)                                        # kernel time includes idle time
        return total - n(idle), total
    if sys.platform == "darwin":
        return _mac_cpu_times()
    with open("/proc/stat", encoding="ascii") as f:
        v = [int(x) for x in f.readline().split()[1:9]]
    return sum(v) - v[3] - v[4], sum(v)                                    # everything except idle and waiting on disk


# ---- a Mac has no /proc: the same numbers come from the kernel's host statistics
_mac = {}


def _mach():
    """The system library and this machine's host port, opened once."""
    if not _mac:
        import ctypes
        lib = ctypes.CDLL("/usr/lib/libSystem.dylib")
        lib.mach_host_self.restype = ctypes.c_uint32
        lib.host_statistics.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        lib.host_statistics64.argtypes = lib.host_statistics.argtypes
        _mac.update(lib=lib, host=lib.mach_host_self())
    return _mac["lib"], _mac["host"]


def _mac_cpu_times():
    """(busy, total) processor ticks since start: user, system and nice are busy, idle is not."""
    import ctypes
    lib, host = _mach()
    ticks = (ctypes.c_uint32 * 4)()                     # user, system, idle, nice
    count = ctypes.c_uint32(4)
    if lib.host_statistics(host, 3, ticks, ctypes.byref(count)) != 0:   # 3 = HOST_CPU_LOAD_INFO
        raise OSError("host_statistics failed")
    user, system, idle, nice = ticks
    return user + system + nice, user + system + idle + nice


def _mac_ram_free_gb() -> float:
    """Memory that can be had without swapping: free, inactive and speculative pages, as macOS counts them."""
    import ctypes
    n, q = ctypes.c_uint32, ctypes.c_uint64

    class VM(ctypes.Structure):                         # vm_statistics64
        _fields_ = [("free", n), ("active", n), ("inactive", n), ("wire", n), ("zero_fill", q), ("reactivations", q),
                    ("pageins", q), ("pageouts", q), ("faults", q), ("cow_faults", q), ("lookups", q), ("hits", q),
                    ("purges", q), ("purgeable", n), ("speculative", n), ("decompressions", q), ("compressions", q),
                    ("swapins", q), ("swapouts", q), ("compressor", n), ("throttled", n), ("external", n),
                    ("internal", n), ("uncompressed_in_compressor", q)]
    lib, host = _mach()
    vm = VM()
    count = ctypes.c_uint32(ctypes.sizeof(VM) // 4)
    if lib.host_statistics64(host, 4, ctypes.byref(vm), ctypes.byref(count)) != 0:   # 4 = HOST_VM_INFO64
        raise OSError("host_statistics64 failed")
    return (vm.free + vm.inactive + vm.speculative) * os.sysconf("SC_PAGE_SIZE") / 1e9


def _ram_free_gb() -> float:
    if os.name == "nt":
        import ctypes

        class M(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
                (n, ctypes.c_ulonglong) for n in ("total", "avail", "tpf", "apf", "tv", "av", "aev")]
        m = M()
        m.dwLength = ctypes.sizeof(M)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.avail / 1e9
    if sys.platform == "darwin":
        return _mac_ram_free_gb()
    with open("/proc/meminfo", encoding="ascii") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1e6
    return 99.0


def _watch():
    try:
        last = _cpu_times()
    except Exception:  # noqa: BLE001 - a system whose processor we cannot measure: leave that out, keep the rest
        last = None
    while True:
        time.sleep(1)
        if last is not None:
            try:
                now = _cpu_times()
                used, total = now[0] - last[0], now[1] - last[1]
                last = now
                if total > 0:
                    # smoothed over a few seconds, so one short spike neither holds people up nor lets too much in
                    _state["cpu"] = 0.55 * _state["cpu"] + 0.45 * (100.0 * used / total)
            except Exception:  # noqa: BLE001
                pass
        try:
            _state["ram_free"] = _ram_free_gb()
        except Exception:  # noqa: BLE001
            pass
        try:
            if time.time() - _state["at"] > 15:
                _state["disk_free"] = shutil.disk_usage(config.DATA_DIR).free / 1e9
                _state["at"] = time.time()
        except Exception:  # noqa: BLE001
            pass


def start():
    global _started
    with _lock:
        if not _started:
            _started = True
            threading.Thread(target=_watch, daemon=True, name="load").start()


def busy() -> bool:
    """True while the machine is close to full: nothing extra should start right now."""
    if _force is not None:
        return _force
    start()
    return _state["cpu"] >= BUSY_CPU or _state["ram_free"] < MIN_FREE_RAM_GB


def disk_full() -> bool:
    start()
    return _state["disk_free"] < MIN_FREE_DISK_GB


def state() -> dict:
    start()
    return {"cpu": round(_state["cpu"]), "ram_free_gb": round(_state["ram_free"], 1), "disk_free_gb": round(_state["disk_free"], 1),
            "busy": busy(), "busy_cpu": BUSY_CPU}
