#!/usr/bin/env python3
"""Drive a local Safari workload while retaining browser and guest health evidence."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import subprocess
import threading
import time

from reims_qmp import ROOT, identified_run, QMP


def sample_guest(ssh, qmp_path):
    try:
        sample = subprocess.run([*ssh, "uptime; stat -f %Su /dev/console"], capture_output=True, timeout=8)
        ssh_ok, output = sample.returncode == 0, sample.stdout.decode(errors="replace")
    except (OSError, subprocess.TimeoutExpired) as error:
        ssh_ok, output = False, type(error).__name__
    try:
        with QMP(qmp_path) as qmp:
            status = qmp.execute("query-status")
    except (OSError, EOFError, ValueError, RuntimeError) as error:
        status = {"running": False, "status": "unavailable", "error": type(error).__name__}
    return {"ssh_ok": ssh_ok, "guest": output, "status": status}


def browser_evidence(reports, seconds):
    """Require correct pixels and continuous browser activity across the run."""
    if len(reports) < seconds / 10 or not reports:
        return False
    try:
        return (all(report.get("webglPass") is True for report in reports)
                and reports[0]["elapsedSeconds"] <= 10
                and reports[-1]["elapsedSeconds"] >= seconds - 10
                and all(0 < right["host_monotonic"] - left["host_monotonic"] <= 10
                        and right["frames"] > left["frames"]
                        for left, right in zip(reports, reports[1:])))
    except (KeyError, TypeError):
        return False


def stress(seconds, port):
    run = identified_run(ROOT / "vendor/reims-lab/runtime/current")
    ssh_port = int((run / "ssh-port").read_text())
    page = (ROOT / "setup/probes/browser-smoke.html").read_bytes()
    reports, health = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path != "/":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if self.path != "/metrics" or not 0 < size <= 16384:
                    raise ValueError("Invalid telemetry")
                report = json.loads(self.rfile.read(size))
                if not isinstance(report, dict):
                    raise ValueError("Expected an object")
            except ValueError:
                self.send_error(400)
                return
            report["host_monotonic"] = time.monotonic()
            reports.append(report)
            with (run / "browser-telemetry.jsonl").open("a") as output:
                output.write(json.dumps(report) + "\n")
            self.send_response(204)
            self.end_headers()

    server = HTTPServer(("127.0.0.1", port), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "-p", str(ssh_port), "azel@127.0.0.1"]
    started = time.monotonic()
    try:
        subprocess.run([*ssh, f"open -a Safari http://10.0.2.2:{port}/"], check=True, timeout=15)
        deadline = started + seconds
        while True:
            item = sample_guest(ssh, run / "qmp.sock")
            item["elapsed_seconds"] = round(time.monotonic() - started, 2)
            status = item["status"]
            health.append(item)
            (run / "browser-health.json").write_text(json.dumps(health, indent=2) + "\n")
            print(json.dumps({"elapsed": item["elapsed_seconds"], "ssh_ok": item["ssh_ok"],
                              "qemu": status["status"], "browser_reports": len(reports)}), flush=True)
            if not item["ssh_ok"] or not status["running"]:
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(min(30, max(0, deadline-time.monotonic())))
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
    elapsed = time.monotonic() - started
    panic = "panic(" in (run / "serial.log").read_text(errors="replace")
    passed = elapsed >= seconds and not panic and bool(health) and all(s["ssh_ok"] and s["status"]["running"] for s in health)
    passed = passed and browser_evidence(reports, seconds)
    result = {"pass": passed, "elapsed_seconds": round(elapsed, 2), "kernel_panic": panic,
              "browser_probe_sha256": hashlib.sha256(page).hexdigest(),
              "health_samples": len(health), "browser_reports": len(reports),
              "last_browser_report": reports[-1] if reports else None,
              "scope": "Local Safari WebGL draw/readback and animated layers; frame callback rate is not displayed FPS"}
    (run / "browser-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600 or not 1024 <= args.port <= 65535:
        parser.error("seconds must be 1..3600 and port 1024..65535")
    raise SystemExit(stress(args.seconds, args.port))
