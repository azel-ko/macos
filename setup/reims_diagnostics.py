"""Retain diagnostic identifiers and counts without guest shader text."""
from collections import Counter
import json
import re


def retained_pid(run):
    """QEMU removes its pidfile on clean exit; use only this run's prior record."""
    try:
        pid = int((run / "qemu.pid").read_text())
    except FileNotFoundError:
        try:
            previous = json.loads((run / "gpu-diagnostics.json").read_text())
            pid = previous.get("qemu_pid") if previous.get("run") == run.name else None
        except (OSError, ValueError):
            pid = None
    return pid if isinstance(pid, int) and pid > 1 else None


def vulkan_summary(lines):
    vuids = Counter()
    lost = fatal = 0
    for line in lines:
        vuids.update(re.findall(r"\bVUID-[A-Za-z0-9_-]+", line))
        lost += bool(re.search(r"Vulkan device was lost|VK_ERROR_DEVICE_LOST", line))
        fatal += "reims-vgpu: fatal:" in line
    return {"validation_ids": dict(sorted(vuids.items())),
            "device_lost_lines": lost, "fatal_lines": fatal}


def own_gpu_hangs(entries, pid):
    """Count only kernel GPU HANG entries that explicitly name this QEMU PID."""
    result = []
    for entry in entries:
        message = entry.get("MESSAGE", "")
        if isinstance(message, str) and "GPU HANG" in message and re.search(
                rf"\bqemu-system-\S+\s+\[{int(pid)}\]", message):
            # Keep a diagnostic code and time; no raw kernel or shader dump.
            code = re.search(r"ecode\s+([0-9a-fA-F:]+)", message)
            result.append({"journal_realtime_us": entry.get("__REALTIME_TIMESTAMP"),
                           "ecode": code[1] if code else None})
    return result
