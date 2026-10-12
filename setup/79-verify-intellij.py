#!/usr/bin/env python3
"""Exercise an authored file in IntelliJ; retain host frames for visual review."""
import importlib.util
import json
import shlex
import subprocess
import time
import uuid

from reims_qmp import ROOT, identified_run, QMP
from reims_visual import editor_target, ide_file_opened


def verify():
    run = identified_run(ROOT / "vendor/reims-lab/runtime/current")
    (run / "intellij-result.json").write_text('{"input_save_pass": false, "status": "incomplete"}\n')
    port = int((run / "ssh-port").read_text())
    if not 1024 <= port <= 65535:
        raise ValueError("Invalid guest SSH port")
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-p", str(port), "azel@127.0.0.1"]

    def guest(command, data=None):
        return subprocess.run([*ssh, command], input=data, check=True, capture_output=True, timeout=20).stdout

    if guest("stat -f %Su /dev/console").strip() != b"azel":
        raise RuntimeError("Log in to the graphical desktop first")
    filename = "reims-ide-" + uuid.uuid4().hex[:12] + ".txt"
    (run / "intellij-result.json").write_text(json.dumps({"input_save_pass": False,
        "status": "incomplete", "fixture_file": filename}) + "\n")
    path = "/Users/azel/" + filename
    fixture = "".join(f"REIMS LINE {i:04d} — editor paint and scroll check\n" for i in range(500))
    guest("cat > " + shlex.quote(path), fixture.encode())
    guest("open -na 'IntelliJ IDEA.app' --args -e " + shlex.quote(path))
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        log = guest('tail -c 262144 "$HOME/Library/Logs/JetBrains/IntelliJIdea2026.2/idea.log"')
        if ide_file_opened(log.decode(errors="replace"), filename):
            break
        time.sleep(2)
    else:
        raise TimeoutError("IntelliJ did not report opening the authored test file")
    # AppKit queries the front application without scripting System Events or
    # granting Accessibility access to the guest automation process.
    query = 'ObjC.import("AppKit"); $.NSWorkspace.sharedWorkspace.frontmostApplication.bundleIdentifier.js'
    front = guest("osascript -l JavaScript -e " + shlex.quote(query)).decode().strip()
    if not front.startswith("com.jetbrains.intellij"):
        raise RuntimeError(f"IntelliJ is not frontmost: {front}")
    spec = importlib.util.spec_from_file_location("reims_capture", ROOT / "setup/76-capture-reims.py")
    capture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture)
    time.sleep(2)
    frames = [capture.capture().name]
    source_path, binary = path + ".window.m", path + ".window"
    guest("cat > " + shlex.quote(source_path), (ROOT / "setup/probes/ide-window.m").read_bytes())
    guest("xcrun clang -fobjc-arc -fno-modules -framework Foundation -framework CoreGraphics "
          + shlex.quote(source_path) + " -o " + shlex.quote(binary))
    pid = guest("pgrep -x idea").decode().strip()
    if not pid.isdigit():
        raise RuntimeError("Expected one IntelliJ process")
    geometry = json.loads(guest(shlex.quote(binary) + " " + pid))
    (run / "intellij-windows.json").write_text(json.dumps(geometry, indent=2) + "\n")
    x, y = editor_target(geometry)
    with QMP(run / "qmp.sock") as qmp:
        qmp.execute("input-send-event", {"events": [
            {"type": "abs", "data": {"axis": "x", "value": x}},
            {"type": "abs", "data": {"axis": "y", "value": y}},
            {"type": "btn", "data": {"button": "left", "down": True}}]})
        time.sleep(.05)
        qmp.execute("input-send-event", {"events": [
            {"type": "btn", "data": {"button": "left", "down": False}}]})
        time.sleep(.2)
        for _ in range(16):
            qmp.execute("input-send-event", {"events": [
                {"type": "btn", "data": {"button": "wheel-down", "down": True}},
                {"type": "btn", "data": {"button": "wheel-down", "down": False}}]})
            time.sleep(.03)
        time.sleep(1)
        frames.append(capture.capture().name)
        for _ in range(16):
            qmp.execute("input-send-event", {"events": [
                {"type": "btn", "data": {"button": "wheel-up", "down": True}},
                {"type": "btn", "data": {"button": "wheel-up", "down": False}}]})
            time.sleep(.03)
        time.sleep(1)
        started = time.monotonic()
        for key in ["meta_l-a", *"reimsidecheck", "ret", "meta_l-s"]:
            qmp.hmp("sendkey " + key + " 30")
            time.sleep(.1)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        content = guest("cat " + shlex.quote(path))
        if content == b"reimsidecheck\n":
            break
        time.sleep(.5)
    frames.append(capture.capture().name)
    output = {"input_save_pass": content == b"reimsidecheck\n", "file_open_pass": True,
              "front_bundle": front, "input_save_elapsed_seconds": round(time.monotonic() - started, 3),
              "captures": frames, "fixture_file": filename, "editor_geometry": geometry,
              "visual_verdict": "requires human review of the host-owned captures",
              "scope": "LightEdit open, mouse-wheel scrolling and keyboard save; not project indexing or compilation"}
    (run / "intellij-result.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))
    return 0 if output["input_save_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(verify())
