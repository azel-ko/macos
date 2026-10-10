#!/usr/bin/env python3
"""Run the authored Metal probe in the logged-in GUI bootstrap domain."""
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import time
import uuid

from reims_qmp import ROOT, identified_run


def verify():
    run = identified_run(ROOT / "vendor/reims-lab/runtime/current")
    port = int((run / "ssh-port").read_text())
    if not 1024 <= port <= 65535:
        raise RuntimeError("Invalid test SSH port")
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-p", str(port), "azel@127.0.0.1"]

    def guest(command, data=None, check=True):
        return subprocess.run([*ssh, command], input=data, check=check,
                              capture_output=True, timeout=15)

    uid = int(guest("id -u").stdout)
    console = guest("stat -f %Su /dev/console").stdout.decode().strip()
    if console != "azel":
        raise RuntimeError("The test user must be logged in to the graphical desktop")
    guest(f"launchctl print gui/{uid}")
    label = "org.azel.metal-smoke." + run.name + "." + uuid.uuid4().hex[:12]
    base = "/Users/azel/" + label
    plist_path, output, errors = base + ".plist", base + ".json", base + ".stderr"
    plist = {
        "Label": label, "ProgramArguments": ["/Users/azel/metal-smoke", "--gui"],
        "RunAtLoad": True, "StandardOutPath": output, "StandardErrorPath": errors,
        "LimitLoadToSessionType": "Aqua",
    }
    # A unique service per identified overlay; never replace a user's agent.
    guest(f"test ! -e {plist_path} && cat > {plist_path}", plistlib.dumps(plist))
    launched = False
    try:
        guest(f"launchctl bootstrap gui/{uid} {plist_path}")
        launched = True
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            probe = guest(f"cat {output}", check=False)
            if probe.returncode == 0 and probe.stdout.strip():
                result = json.loads(probe.stdout)
                report = {"pass": result.get("pass") is True and bool(result.get("systemDefaultDeviceAvailable"))
                          and bool(result.get("windowServerAttached")),
                          "bootstrap_domain": f"gui/{uid}", "console_user": console, "guest": result}
                (run / "verification-gui.json").write_text(json.dumps(report, indent=2) + "\n")
                (run / "metal-smoke-gui.stderr").write_bytes(guest(f"cat {errors}", check=False).stdout)
                print(json.dumps(report, indent=2))
                return 0 if report["pass"] else 1
            time.sleep(1)
        raise TimeoutError("GUI Metal probe did not complete within 75 seconds")
    finally:
        if launched:
            guest(f"launchctl bootout gui/{uid}/{label}", check=False)
        # Keep guest output for diagnosis, remove only the authored job plist.
        guest(f"rm -f {plist_path}", check=False)


if __name__ == "__main__":
    try:
        sys.exit(verify())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(f"GUI GPU verification incomplete: {error}")
