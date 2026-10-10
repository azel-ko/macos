#!/usr/bin/env python3
"""Copy an offline existing macOS installation into an independent GPU lab."""
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE).stdout


def prepare(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    disk = source / "mac_hdd_ng.img"
    files = {
        "OpenCore.qcow2": source / "OpenCore/OpenCore.qcow2",
        "OVMF_CODE.fd": source / "OVMF_CODE_4M.fd",
        "OVMF_VARS.fd": source / "OVMF_VARS_4M.macvm.fd",
    }
    for path in [disk, *files.values()]:
        if not path.is_file():
            raise RuntimeError(f"Missing source: {path}")
    if destination.exists():
        raise RuntimeError(f"Destination already exists; refusing to overwrite: {destination}")
    # The normal launcher takes this same lock before starting QEMU.
    with Path(str(disk) + ".launch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Never use -U: qemu-img must also reject an active external writer.
        info = json.loads(run("qemu-img", "info", "--output=json", str(disk)))
        destination.mkdir(parents=True)
        temporary = destination / "macos-copy-incomplete.qcow2"
        base = destination / "macos-base.qcow2"
        print("Converting the offline current state (internal snapshots stay on the original).", flush=True)
        run("qemu-img", "convert", "-f", "qcow2", "-O", "qcow2", str(disk), str(temporary))
        print("Comparing all guest-visible disk contents.", flush=True)
        comparison = run("qemu-img", "compare", "-f", "qcow2", "-F", "qcow2", str(disk), str(temporary))
        run("qemu-img", "check", str(temporary))
        temporary.rename(base)
        hashes = {}
        for name, path in files.items():
            target = destination / name
            shutil.copyfile(path, target)
            hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
            target.chmod(0o444)
        base.chmod(0o444)
        manifest = {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "guest": "existing macOS Sonoma 14.8.8",
            "source": str(disk),
            "source_info": info,
            "base": str(base),
            "comparison": comparison.strip(),
            "firmware_sha256": hashes,
            "base_info": json.loads(run("qemu-img", "info", "--output=json", str(base))),
        }
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"Independent read-only base ready: {base}", flush=True)


if __name__ == "__main__":
    try:
        prepare(ROOT / "vendor/OSX-KVM", ROOT / "vendor/reims-lab/base")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f"Preparation failed; original was not modified: {error}")
