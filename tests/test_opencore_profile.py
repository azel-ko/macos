import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("opencore_profile", ROOT / "setup/75-opencore-profile.py")
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class ProfileTests(unittest.TestCase):
    def test_reuses_only_a_matching_unmodified_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "base.qcow2"
            source.write_bytes(b"base")
            destination = root / "profile"
            destination.mkdir()
            output = destination / "OpenCore.qcow2"
            output.write_bytes(b"configured")
            memory_profile = ROOT / "conf/reims-opencore.json"
            changes = {k: {"before": not v, "after": v} for k, v in profile.read_profile(memory_profile).items()}
            manifest = {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                        "changes": {"booter_quirks": changes}}
            (destination / "manifest.json").write_text(json.dumps(manifest))
            self.assertEqual(profile.ensure_profile(source, destination, memory_profile), output)
            output.write_bytes(b"unreviewed changes")
            with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                profile.ensure_profile(source, destination, memory_profile)
            self.assertEqual(output.read_bytes(), b"unreviewed changes")

    def test_only_the_requested_enabled_kext_changes(self):
        original = {"Kernel": {"Add": [{"BundlePath": "Lilu.kext", "Enabled": True},
                                       {"BundlePath": "WhateverGreen.kext", "Enabled": True}]},
                    "Booter": {"Quirks": {"SetupVirtualMap": False}}}
        changed = copy.deepcopy(original)
        profile.disable_kext(changed, "WhateverGreen.kext")
        original["Kernel"]["Add"][1]["Enabled"] = False
        self.assertEqual(changed, original)
        with self.assertRaises(ValueError):
            profile.disable_kext(changed, "WhateverGreen.kext")
        with self.assertRaises(ValueError):
            profile.disable_kext(changed, "Missing.kext")

    def test_partition_offset_comes_from_validated_gpt(self):
        table = bytearray(128)
        table[:16] = profile.ESP
        struct.pack_into("<Q", table, 32, 8)
        header = bytearray(512)
        header[:8] = b"EFI PART"
        struct.pack_into("<II", header, 8, 0x10000, 92)
        struct.pack_into("<QIII", header, 72, 2, 1, 128, zlib.crc32(table))
        struct.pack_into("<I", header, 16, zlib.crc32(header[:92]))
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "boot.raw"
            raw.write_bytes(bytes(512) + header + table + bytes(8192))
            self.assertEqual(profile.esp_offset(raw), 4096)
            broken = bytearray(raw.read_bytes())
            broken[1024 + 32] ^= 1
            raw.write_bytes(broken)
            with self.assertRaisesRegex(ValueError, "partition table checksum"):
                profile.esp_offset(raw)
