#!/usr/bin/env python3
"""Summarize a lab run's Vulkan errors and its own kernel GPU HANG events."""
import argparse
import json
from pathlib import Path
import subprocess
import time

from reims_diagnostics import own_gpu_hangs, retained_pid, vulkan_summary
from reims_qmp import ROOT, identified_run


def diagnose(run):
    run = Path(run).resolve(strict=True)
    runtime = (ROOT / "vendor/reims-lab/runtime").resolve(strict=True)
    if run.parent != runtime or not run.name.startswith("run-"):
        raise ValueError("Expected an existing lab run directory")
    config = run / "config.json"
    pid = retained_pid(run)
    try:
        identified_run(run)
        until = time.time()
    except (OSError, ValueError, RuntimeError):
        # A dead PID may later be reused. Bound the journal query by this run's
        # retained outputs, rather than all subsequent host activity.
        until = max((run / name).stat().st_mtime for name in ["qemu.log", "serial.log"]) + 60
    with (run / "qemu.log").open(errors="replace") as log:
        summary = vulkan_summary(log)
    command = ["journalctl", "-k", "--no-pager", "-o", "json", "--grep", "GPU HANG",
               "--since", f"@{config.stat().st_mtime:.6f}", "--until", f"@{until:.6f}"]
    try:
        if pid is None:
            raise ValueError("No retained QEMU PID")
        query = subprocess.run(command, capture_output=True, text=True, timeout=20)
        # journalctl returns 1 when the --grep selection has no entries.
        available = query.returncode in (0, 1) and not query.stderr.strip()
        entries = [json.loads(line) for line in query.stdout.splitlines() if line.startswith("{")]
        hangs = own_gpu_hangs(entries, pid)
        journal = {"query_ok": available, "own_gpu_hangs": hangs,
                   "error": None if available else "Kernel journal query incomplete or permission denied"}
    except (OSError, subprocess.SubprocessError, ValueError):
        journal = {"query_ok": False, "own_gpu_hangs": [], "error": "Kernel journal query unavailable"}
    result = {"run": run.name, "qemu_pid": pid, "vulkan": summary, "kernel_journal": journal,
              "vulkan_diagnostics": json.loads(config.read_text()).get("vulkan_diagnostics", {}),
              "layer_message_capture_verified": False,
              "validation_note": "Counts cover retained qemu.log only. Beta's upstream callback relay drops driver/layer IDs; no clean validation claim is made.",
              "scope": "Diagnostic evidence only; absence of a recorded error is not a stability pass"}
    (run / "gpu-diagnostics.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default=ROOT / "vendor/reims-lab/runtime/current")
    diagnose(parser.parse_args().run)
