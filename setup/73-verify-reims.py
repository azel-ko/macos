#!/usr/bin/env python3
"""Verify guest Metal results and the actual Vulkan driver in its QEMU process."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from reims_qmp import identified_run

ROOT = Path(__file__).resolve().parents[1]


def engine_times(pid):
    counters = {}
    for path in Path(f"/proc/{pid}/fdinfo").glob("*"):
        try:
            content = path.read_text()
        except OSError:
            continue
        # A client can expose several FDs: count each DRM client only once.
        client = re.search(r"^drm-client-id:\s*(\d+)", content, re.M)
        if client:
            counters[client[1]] = {
                name: int(ns) for name, ns in re.findall(r"^drm-engine-([^:]+):\s*(\d+) ns", content, re.M)
            }
    return counters


def verify():
    run = identified_run(ROOT / "vendor/reims-lab/runtime/current")
    pid = int((run / "qemu.pid").read_text())
    port = int((run / "ssh-port").read_text())
    if not 1024 <= port <= 65535:
        raise RuntimeError("Invalid test SSH port")
    options = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new"]
    source = ROOT / "setup/probes/metal-smoke.m"
    subprocess.run(["scp", *options, "-P", str(port), str(source), "azel@127.0.0.1:/Users/azel/metal-smoke.m"],
                   check=True, timeout=30)
    before = engine_times(pid)
    started = time.monotonic()
    probe = subprocess.run(["ssh", *options, "-p", str(port), "azel@127.0.0.1",
                            "xcrun clang -fobjc-arc -fblocks -fno-modules -mmacosx-version-min=14.0 "
                            "-framework Foundation -framework AppKit -framework Metal /Users/azel/metal-smoke.m "
                            "-o /Users/azel/metal-smoke && /Users/azel/metal-smoke"],
                           text=True, capture_output=True, timeout=150)
    (run / "metal-smoke.stdout").write_text(probe.stdout)
    (run / "metal-smoke.stderr").write_text(probe.stderr)
    after = engine_times(pid)
    try:
        guest = json.loads(probe.stdout)
    except json.JSONDecodeError:
        guest = {"pass": False, "error": "Probe did not return JSON; see metal-smoke.stderr"}
    maps = Path(f"/proc/{pid}/maps").read_text()
    log = Path("/tmp/reims-vgpu-fail.log").read_text(errors="replace")
    caps = [line for line in log.splitlines() if "vk_caps " in line]
    intel = "libvulkan_intel.so" in maps and any("Iris" in line for line in caps)
    delta = {client: {engine: ns - before.get(client, {}).get(engine, ns)
                      for engine, ns in values.items()} for client, values in after.items()}
    result = {
        "pass": probe.returncode == 0 and guest.get("pass") is True and intel,
        "guest": guest, "guest_exit_code": probe.returncode,
        "host_intel_vulkan_driver_loaded": "libvulkan_intel.so" in maps,
        "host_iris_xe_selected": intel, "host_vk_caps": caps,
        "host_drm_engine_delta_ns": delta,
        "elapsed_seconds_including_compile": round(time.monotonic() - started, 3),
        "probe_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "run": str(run),
    }
    (run / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    (run / "device.log").write_text(log)
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    try:
        sys.exit(verify())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(f"GPU verification incomplete: {error}")
