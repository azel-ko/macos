import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))
from reims_beta import verified_build, repair_local_sysroot


class BetaBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lab, self.cache = self.root / "lab", self.root / "cache"
        (self.root / "conf").mkdir()
        self.pins = {"reims_vgpu": "pinned-source", "qemu": "pinned-qemu"}
        (self.root / "conf/reims-beta.lock").write_text(json.dumps(self.pins))
        self.manifest = {"source_pins": self.pins}
        for key, path in [("qemu", self.cache / "qemu/qemu-system-x86_64"),
                          ("rom", self.lab / "beta-dist/share/reims-vgpu/ReimsVgpu.rom")]:
            path.parent.mkdir(parents=True)
            path.write_bytes(key.encode())
            self.manifest[key] = str(path)
            self.manifest[key + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.record()

    def record(self):
        (self.lab / "beta-dist/build-manifest.json").write_text(json.dumps(self.manifest))

    def test_accepts_exact_pinned_pair(self):
        self.assertEqual(verified_build(self.root, self.lab, self.cache), self.manifest)

    def test_runtime_patch_change_invalidates_the_recorded_build(self):
        self.pins.update(local_patch="source.patch", metal2vulkan_patch="runtime.patch")
        for name in ("source.patch", "runtime.patch"):
            (self.root / name).write_bytes(name.encode())
        (self.root / "conf/reims-beta.lock").write_text(json.dumps(self.pins))
        self.manifest.update(source_pins=self.pins,
            source_patch_sha256=hashlib.sha256((self.root / "source.patch").read_bytes()).hexdigest(),
            metal2vulkan_patch_sha256=hashlib.sha256((self.root / "runtime.patch").read_bytes()).hexdigest())
        self.record()
        verified_build(self.root, self.lab, self.cache)
        (self.root / "runtime.patch").write_bytes(b"modified")
        with self.assertRaisesRegex(RuntimeError, "translator patch hash mismatch"):
            verified_build(self.root, self.lab, self.cache)

    def test_extracted_pkgconfig_is_relocated_without_overwriting_host_files(self):
        sysroot = self.root / "sysroot"
        folder = sysroot / "usr/lib/x86_64-linux-gnu"
        folder.mkdir(parents=True)
        pc = folder / "sample.pc"
        pc.write_text("prefix=/usr\nName: sample\n")
        host = self.root / "host"
        host.mkdir()
        (host / "libsample.so.1").write_bytes(b"runtime")
        (folder / "libsample.so").symlink_to("libsample.so.1")
        repair_local_sysroot(sysroot, host)
        self.assertEqual(pc.read_text(), f"prefix={sysroot / 'usr'}\nName: sample\n")
        self.assertEqual((folder / "libsample.so").read_bytes(), b"runtime")
        self.assertEqual((host / "libsample.so.1").read_bytes(), b"runtime")
        repair_local_sysroot(sysroot, host)

    def test_rejects_binary_rom_pin_and_path_mismatches(self):
        for key in ("qemu", "rom"):
            with self.subTest(key=key):
                path = Path(self.manifest[key])
                original = path.read_bytes()
                path.write_bytes(b"different")
                with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                    verified_build(self.root, self.lab, self.cache)
                path.write_bytes(original)
        self.manifest["source_pins"] = {"qemu": "other"}
        self.record()
        with self.assertRaisesRegex(RuntimeError, "source pins differ"):
            verified_build(self.root, self.lab, self.cache)
        self.manifest["source_pins"] = self.pins
        self.manifest["rom"] = str(self.root / "other.rom")
        self.record()
        with self.assertRaisesRegex(RuntimeError, "path or hash mismatch"):
            verified_build(self.root, self.lab, self.cache)
