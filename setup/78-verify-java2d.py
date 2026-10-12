#!/usr/bin/env python3
"""Verify Java2D screen pixels and input using the installed IntelliJ runtime."""
import importlib.util
import json
from pathlib import Path
import plistlib
import shlex
import subprocess
import time
import uuid

from PIL import Image
from reims_qmp import ROOT, identified_run, QMP
from reims_visual import palette_evidence


def verify():
    run = identified_run(ROOT / "vendor/reims-lab/runtime/current")
    (run / "java2d-result.json").write_text('{"pass": false, "status": "incomplete"}\n')
    port = int((run / "ssh-port").read_text())
    if not 1024 <= port <= 65535:
        raise ValueError("Invalid guest SSH port")
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-p", str(port), "azel@127.0.0.1"]

    def guest(command, data=None, check=True):
        return subprocess.run([*ssh, command], input=data, capture_output=True, check=check, timeout=30)

    if guest("stat -f %Su /dev/console").stdout.strip() != b"azel":
        raise RuntimeError("Log in to the test desktop first")
    uid = int(guest("id -u").stdout)
    token = "org.azel.java2d." + uuid.uuid4().hex
    base = "/Users/azel/" + token
    guest("mkdir " + base)
    source = (ROOT / "setup/probes/SwingRenderProbe.java").read_bytes()
    guest("cat > " + base + "/SwingRenderProbe.java", source)
    jbr = "/Applications/IntelliJ IDEA.app/Contents/jbr/Contents/Home/bin/"
    guest(shlex.quote(jbr + "javac") + " " + base + "/SwingRenderProbe.java")
    plist = {"Label": token, "ProgramArguments": [jbr + "java", "-Dsun.java2d.metal=true", "-cp", base,
              "SwingRenderProbe", base + "/result.json"], "RunAtLoad": True,
              "LimitLoadToSessionType": "Aqua", "StandardOutPath": base + "/stdout",
              "StandardErrorPath": base + "/stderr"}
    guest("cat > " + base + "/job.plist", plistlib.dumps(plist))
    launched = False
    try:
        guest(f"launchctl bootstrap gui/{uid} {base}/job.plist")
        launched = True
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            result = guest("cat " + base + "/result.json", check=False)
            if result.returncode == 0:
                json.loads(result.stdout)
                break
            time.sleep(1)
        else:
            raise TimeoutError("Java2D fixture did not become ready")
        with QMP(run / "qmp.sock") as qmp:
            for key in ["meta_l-a", *"reimsgpucheck"]:
                qmp.hmp("sendkey " + key + " 30")
                time.sleep(.1)
        time.sleep(1)
        report = json.loads(guest("cat " + base + "/result.json").stdout)
        spec = importlib.util.spec_from_file_location("reims_capture", ROOT / "setup/76-capture-reims.py")
        capture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(capture)
        screenshot = capture.capture()
        with Image.open(screenshot) as image:
            colors = palette_evidence(image, report)
        metal = report.get("graphicsConfiguration", "").endswith("MTLGraphicsConfig")
        output = {"pass": colors["pass"] and report["inputPass"] and metal, "metal_pipeline": metal, "fixture": report,
                  "colors": colors, "capture": screenshot.name,
                  "scope": "JBR Java2D six screen colors and keyboard input; not display FPS or full IDE acceptance"}
        (run / "java2d-result.json").write_text(json.dumps(output, indent=2) + "\n")
        print(json.dumps(output, indent=2))
        return 0 if output["pass"] else 1
    finally:
        if launched:
            guest(f"launchctl bootout gui/{uid}/{token}", check=False)
        # Retain only this fixture's outputs in its unique guest directory.


if __name__ == "__main__":
    raise SystemExit(verify())
