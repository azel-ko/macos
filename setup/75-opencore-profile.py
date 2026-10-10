#!/usr/bin/env python3
"""Create an independent OpenCore disk for a declared configuration comparison."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import tempfile
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
ESP = uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b").bytes_le
MEMORY_QUIRKS = ("EnableWriteUnprotector", "RebuildAppleMemoryMap", "SyncRuntimePermissions", "ProvideCustomSlide")


def read_profile(path):
    values = json.loads(path.read_text())["booter_quirks"]
    if set(values) != set(MEMORY_QUIRKS) or any(type(value) is not bool for value in values.values()):
        raise ValueError("Expected exactly four boolean memory quirks")
    return values


def ensure_profile(source, destination, memory_profile):
    expected = read_profile(memory_profile)
    if not destination.exists():
        return prepare(source, destination, memory_profile=memory_profile)
    output = destination / "OpenCore.qcow2"
    manifest = json.loads((destination / "manifest.json").read_text())
    changes = manifest["changes"]
    actual = {key: item["after"] for key, item in changes.get("booter_quirks", {}).items()}
    if set(changes) != {"booter_quirks"} or actual != expected:
        raise RuntimeError("Existing OpenCore profile has different changes; refusing to overwrite")
    if (manifest["source_sha256"] != hashlib.sha256(source.read_bytes()).hexdigest()
            or manifest["output_sha256"] != hashlib.sha256(output.read_bytes()).hexdigest()):
        raise RuntimeError("Existing OpenCore profile hash mismatch; refusing to overwrite")
    return output


def esp_offset(raw):
    with raw.open("rb") as disk:
        disk.seek(512)
        header = bytearray(disk.read(512))
        if header[:8] != b"EFI PART":
            raise ValueError("Expected a GPT OpenCore image")
        size, crc = struct.unpack_from("<II", header, 12)
        if not 92 <= size <= 512:
            raise ValueError("Invalid GPT header size")
        header[16:20] = bytes(4)
        if zlib.crc32(header[:size]) != crc:
            raise ValueError("Invalid GPT header checksum")
        lba, count, entry_size, table_crc = struct.unpack_from("<QIII", header, 72)
        if not 1 <= count <= 4096 or not 128 <= entry_size <= 4096:
            raise ValueError("Invalid GPT partition table geometry")
        disk.seek(lba * 512)
        entries = disk.read(count * entry_size)
        if len(entries) != count * entry_size or zlib.crc32(entries) != table_crc:
            raise ValueError("Invalid GPT partition table checksum")
        offsets = [struct.unpack_from("<Q", entries, i + 32)[0] * 512
                   for i in range(0, len(entries), entry_size) if entries[i:i+16] == ESP]
        if len(offsets) != 1 or not 512 <= offsets[0] < raw.stat().st_size:
            raise ValueError("Expected one EFI system partition")
        return offsets[0]


def disable_kext(config, name):
    matches = [entry for entry in config["Kernel"]["Add"] if entry["BundlePath"] == name]
    if len(matches) != 1 or matches[0]["Enabled"] is not True:
        raise ValueError("Expected exactly one enabled kext matching the requested BundlePath")
    matches[0]["Enabled"] = False


def prepare(source, destination, kext=None, booter_quirks_from=None, memory_profile=None):
    if kext is None and booter_quirks_from is None and memory_profile is None:
        raise ValueError("Specify a profile change")
    if destination.exists():
        raise FileExistsError("Profile destination already exists")
    destination.mkdir(parents=True)
    with tempfile.TemporaryDirectory(dir=destination) as tmp:
        raw, config_path = Path(tmp) / "opencore.raw", Path(tmp) / "config.plist"
        subprocess.run(["qemu-img", "convert", "-f", "qcow2", "-O", "raw", str(source), str(raw)], check=True)
        image = str(raw) + "@@" + str(esp_offset(raw))
        subprocess.run(["mcopy", "-i", image, "::/EFI/OC/config.plist", str(config_path)], check=True)
        original = config_path.read_bytes()
        config = plistlib.loads(original)
        changes = {}
        if kext is not None:
            disable_kext(config, kext)
            changes["disabled_kext"] = kext
        if booter_quirks_from is not None or memory_profile is not None:
            reference = (read_profile(memory_profile) if memory_profile is not None else
                         plistlib.loads(booter_quirks_from.read_bytes())["Booter"]["Quirks"])
            changes["booter_quirks"] = {}
            for key in MEMORY_QUIRKS:
                value = reference[key]
                if type(value) is not bool:
                    raise ValueError("Expected boolean memory quirks")
                changes["booter_quirks"][key] = {"before": config["Booter"]["Quirks"][key], "after": value}
                config["Booter"]["Quirks"][key] = value
        config_path.write_bytes(plistlib.dumps(config, sort_keys=False))
        subprocess.run(["mcopy", "-o", "-i", image, str(config_path), "::/EFI/OC/config.plist"], check=True)
        verify_path = Path(tmp) / "verified.plist"
        subprocess.run(["mcopy", "-i", image, "::/EFI/OC/config.plist", str(verify_path)], check=True)
        if plistlib.loads(verify_path.read_bytes()) != config:
            raise RuntimeError("OpenCore config readback mismatch")
        output = destination / "OpenCore.qcow2"
        subprocess.run(["qemu-img", "convert", "-f", "raw", "-O", "qcow2", str(raw), str(output)], check=True)
        subprocess.run(["qemu-img", "check", "-q", str(output)], check=True)
        manifest = {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                    "config_before_sha256": hashlib.sha256(original).hexdigest(),
                    "config_after_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                    "changes": changes}
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        output.chmod(0o444)
        return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "vendor/reims-lab/base/OpenCore.qcow2")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--disable-kext")
    profiles = parser.add_mutually_exclusive_group()
    profiles.add_argument("--booter-quirks-from", type=Path)
    profiles.add_argument("--memory-profile", type=Path)
    parser.add_argument("--ensure", action="store_true", help="Reuse only an exactly matching, hash-verified memory profile")
    args = parser.parse_args()
    if args.ensure:
        if args.memory_profile is None or args.disable_kext:
            parser.error("--ensure requires --memory-profile and no kext changes")
        print(ensure_profile(args.source.resolve(strict=True), args.output.resolve(), args.memory_profile))
    else:
        print(prepare(args.source.resolve(strict=True), args.output.resolve(), args.disable_kext,
                      args.booter_quirks_from, args.memory_profile))
