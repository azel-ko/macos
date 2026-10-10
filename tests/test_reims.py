import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_reims", ROOT / "setup/71-prepare-reims.py")
prepare_reims = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_reims)


@unittest.skipUnless(shutil.which("qemu-img") and shutil.which("qemu-io"), "QEMU disk tools required")
class IndependentDiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        (self.source / "OpenCore").mkdir(parents=True)
        self.destination = self.root / "base"
        self.disk = self.source / "mac_hdd_ng.img"
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", str(self.disk), "4M"], check=True)
        subprocess.run(["qemu-img", "snapshot", "-c", "old-state", str(self.disk)], check=True)
        subprocess.run(["qemu-io", "-f", "qcow2", "-c", "write -P 0x5a 0 4096", str(self.disk)], check=True, capture_output=True)
        for name in ("OpenCore/OpenCore.qcow2", "OVMF_CODE_4M.fd", "OVMF_VARS_4M.macvm.fd"):
            (self.source / name).write_bytes(name.encode())

    def test_copies_current_contents_without_a_dependency_on_the_original(self):
        before = hashlib.sha256(self.disk.read_bytes()).hexdigest()
        prepare_reims.prepare(self.source, self.destination)
        self.assertEqual(before, hashlib.sha256(self.disk.read_bytes()).hexdigest())
        manifest = json.loads((self.destination / "manifest.json").read_text())
        self.assertNotIn("backing-filename", manifest["base_info"])
        self.assertNotIn("snapshots", manifest["base_info"])
        self.assertIn("Images are identical", manifest["comparison"])
        self.assertEqual((self.destination / "macos-base.qcow2").stat().st_mode & 0o222, 0)
        subprocess.run(["qemu-io", "-r", "-f", "qcow2", "-c", "read -P 0x5a 0 4096",
                        str(self.destination / "macos-base.qcow2")], check=True, capture_output=True)

    def test_rejects_the_running_normal_launcher_lock(self):
        with Path(str(self.disk) + ".launch.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                prepare_reims.prepare(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_refuses_to_overwrite_an_existing_test_environment(self):
        self.destination.mkdir()
        sentinel = self.destination / "keep"
        sentinel.write_text("existing test state")
        with self.assertRaises(RuntimeError):
            prepare_reims.prepare(self.source, self.destination)
        self.assertEqual(sentinel.read_text(), "existing test state")

    def test_missing_firmware_does_not_start_copying(self):
        (self.source / "OVMF_CODE_4M.fd").unlink()
        with self.assertRaises(RuntimeError):
            prepare_reims.prepare(self.source, self.destination)
        self.assertFalse(self.destination.exists())
