#!/usr/bin/env python3
"""Inspect one identified Reims lab VM; retain crash state in its run directory."""
import argparse
import json
from pathlib import Path
import re
import socket

ROOT = Path(__file__).resolve().parents[1]


class QMP:
    def __init__(self, path, timeout=10):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(timeout)
        self.socket.connect(str(path))
        self.stream = self.socket.makefile("rwb")
        self.sequence = 0
        self.events = []
        if "QMP" not in self.read():
            self.close()
            raise RuntimeError("Missing QMP greeting")
        self.execute("qmp_capabilities")

    def read(self):
        line = self.stream.readline()
        if not line:
            raise EOFError("QMP peer closed")
        return json.loads(line)

    def execute(self, command, arguments=None):
        self.sequence += 1
        request = {"execute": command, "id": self.sequence}
        if arguments is not None:
            request["arguments"] = arguments
        self.stream.write((json.dumps(request) + "\n").encode())
        self.stream.flush()
        while True:
            reply = self.read()
            if "event" in reply:
                self.events.append(reply)
                continue
            if reply.get("id") != self.sequence:
                raise RuntimeError("Unexpected QMP response id")
            if "error" in reply:
                raise RuntimeError(f"{command}: {reply['error']}")
            return reply["return"]

    def hmp(self, command, cpu=None):
        arguments = {"command-line": command}
        if cpu is not None:
            arguments["cpu-index"] = cpu
        return self.execute("human-monitor-command", arguments)

    def close(self):
        self.stream.close()
        self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def identified_run(path):
    run = Path(path).resolve(strict=True)
    pid = int((run / "qemu.pid").read_text())
    args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    disk = b"file=" + str(run / "macos.qcow2").encode()
    if not any(disk in arg.split(b",") for arg in args):
        raise RuntimeError("PID does not belong to the selected test disk")
    return run


def panic_addresses(serial):
    """Only exact addresses named by the guest, never inferred physical pages."""
    addresses = re.findall(r"CR2:\s*(0x[0-9a-fA-F]+)|Spinlock\[(0x[0-9a-fA-F]+)\]", serial)
    return sorted({int(a or b, 16) for a, b in addresses if int(a or b, 16) != 0})


def capture(run, stop=False):
    with QMP(run / "qmp.sock") as qmp:
        status = qmp.execute("query-status")
        if stop and status["running"]:
            qmp.execute("stop")
        report = {"status_before": status, "status": qmp.execute("query-status"), "cpus": []}
        addresses = panic_addresses((run / "serial.log").read_text(errors="replace"))
        serial = (run / "serial.log").read_text(errors="replace")
        fault = re.search(r"Fault CPU:\s*0x([0-9a-fA-F]+)", serial)
        panic_cpu = re.search(r"panic\(cpu (\d+)", serial)
        fault_cpu = int(fault[1], 16) if fault else int(panic_cpu[1]) if panic_cpu else 0
        # Keep the VM paused: continuing after a panic destroys the evidence.
        for cpu in qmp.execute("query-cpus-fast"):
            index = cpu["cpu-index"]
            report["cpus"].append({"index": index, "registers": qmp.hmp("info registers", index)})
        report["addresses"] = []
        for address in addresses:
            report["addresses"].append({
                "virtual_address": hex(address),
                "cpu_index": fault_cpu,
                "translation": qmp.hmp(f"gva2gpa {address:#x}", fault_cpu),
                "words": qmp.hmp(f"x /16gx {address & ~63:#x}", fault_cpu),
            })
        report["events"] = qmp.events
    target = run / "crash-state.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default=ROOT / "vendor/reims-lab/runtime/current")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    hmp = sub.add_parser("hmp")
    hmp.add_argument("expression")
    hmp.add_argument("--cpu", type=int)
    sub.add_parser("quit")
    crash = sub.add_parser("capture")
    crash.add_argument("--stop", action="store_true", help="Pause first; do not resume automatically")
    args = parser.parse_args()
    run = identified_run(args.run)
    if args.command == "capture":
        print(capture(run, args.stop))
    else:
        with QMP(run / "qmp.sock") as qmp:
            if args.command == "status":
                print(json.dumps(qmp.execute("query-status")))
            elif args.command == "hmp":
                print(qmp.hmp(args.expression, args.cpu))
            else:
                qmp.execute("quit")


if __name__ == "__main__":
    main()
