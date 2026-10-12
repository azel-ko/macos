import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReimsLaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "vendor/reims-lab/base"
        self.profile = self.root / "vendor/reims-lab/profiles/osx-kvm-memory"
        for path in [self.base, self.profile, self.root / "setup", self.root / "conf", self.root / "patches", self.root / "bin", self.root / "vendor/OSX-KVM"]:
            path.mkdir(parents=True)
        for name in ["setup/72-boot-reims.sh", "setup/75-opencore-profile.py", "setup/reims-env.sh",
                     "setup/reims-beta-env.sh", "setup/reims_beta.py", "conf/reims-beta.lock", "conf/reims-beta-x11.cmake",
                     "conf/vm.env", "conf/reims.lock", "conf/reims-opencore.json", "patches/reims-cached-views.patch",
                     "patches/reims-beta-runtime.patch", "patches/reims-beta-intel-depth.patch"]:
            shutil.copy(ROOT / name, self.root / name)
        # Redirect the external observation sink in the fixture so this test
        # cannot truncate a real GPU VM's live log on the developer's host.
        launcher = self.root / "setup/72-boot-reims.sh"
        launcher.write_text(launcher.read_text().replace("/tmp/reims-vgpu-fail.log", str(self.root / "device.log")))
        for name in ["manifest.json", "macos-base.qcow2", "OVMF_VARS.fd", "OVMF_CODE.fd", "OpenCore.qcow2"]:
            (self.base / name).write_bytes(b"fixture")
        boot = self.profile / "OpenCore.qcow2"
        boot.write_bytes(b"configured")
        values = json.loads((ROOT / "conf/reims-opencore.json").read_text())["booter_quirks"]
        (self.profile / "manifest.json").write_text(json.dumps({
            "source_sha256": hashlib.sha256((self.base / "OpenCore.qcow2").read_bytes()).hexdigest(),
            "output_sha256": hashlib.sha256(boot.read_bytes()).hexdigest(),
            "changes": {"booter_quirks": {key: {"before": not value, "after": value} for key, value in values.items()}},
        }))
        qemu = self.root / "vendor/reims-vgpu/vendor/qemu/build/qemu-system-x86_64"
        qemu.parent.mkdir(parents=True)
        qemu.write_text("#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n")
        qemu.chmod(0o755)
        rom = self.root / "vendor/reims-vgpu/crates/reims-vgpu-efi/out/reims-vgpu-gop.rom"
        rom.parent.mkdir(parents=True)
        rom.write_bytes(b"rom")
        image = self.root / "bin/qemu-img"
        image.write_text("#!/bin/sh\nexit 0\n")
        image.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.root}/bin:{os.environ['PATH']}", VM_CPU_AFFINITY="off")
        self.env["REIMS_STACK"] = "legacy"
        for key in ("REIMS_OPENCORE_FILE", "REIMS_BOOT_PROFILE", "REIMS_RAM_BACKEND", "REIMS_GDB", "REIMS_SHUTDOWN_ACTION"):
            self.env.pop(key, None)

    def beta_fixture(self):
        cache = self.root / "beta-cache"
        qemu = cache / "qemu/qemu-system-x86_64"
        qemu.parent.mkdir(parents=True)
        shutil.copy(self.root / "vendor/reims-vgpu/vendor/qemu/build/qemu-system-x86_64", qemu)
        rom = self.root / "vendor/reims-lab/beta-dist/share/reims-vgpu/ReimsVgpu.rom"
        rom.parent.mkdir(parents=True)
        rom.write_bytes(b"beta-rom")
        manifest = {"source_pins": json.loads((self.root / "conf/reims-beta.lock").read_text()),
                    "source_patch_sha256": hashlib.sha256((self.root / "patches/reims-beta-runtime.patch").read_bytes()).hexdigest(),
                    "metal2vulkan_patch_sha256": hashlib.sha256((self.root / "patches/reims-beta-intel-depth.patch").read_bytes()).hexdigest(),
                    "qemu": str(qemu), "rom": str(rom),
                    "qemu_sha256": hashlib.sha256(qemu.read_bytes()).hexdigest(),
                    "rom_sha256": hashlib.sha256(rom.read_bytes()).hexdigest()}
        (self.root / "vendor/reims-lab/beta-dist/build-manifest.json").write_text(json.dumps(manifest))
        return cache

    def test_beta_uses_verified_device_and_drops_alpha_memory_knobs(self):
        cache = self.beta_fixture()
        (self.root / "device.log").write_text("stale Alpha log")
        result = self.launch(REIMS_STACK="beta", REIMS_BETA_CACHE=str(cache), REIMS_VGPU_GUEST_IMPORT="on")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.arguments()
        device = next(value for value in args if value.startswith("apple-gfx-pci,"))
        self.assertIn("resolution=1920x1080", device)
        self.assertIn("ReimsVgpu.rom", device)
        config = json.loads((self.root / "vendor/reims-lab/runtime/current/config.json").read_text())
        self.assertEqual(config["stack"], "beta")
        self.assertEqual(config["metal2vulkan_patch_sha256"],
                         hashlib.sha256((self.root / "patches/reims-beta-intel-depth.patch").read_bytes()).hexdigest())
        self.assertNotIn("REIMS_VGPU_GUEST_IMPORT", config["switches"])
        self.assertFalse((self.root / "vendor/reims-lab/runtime/current/device.log").exists())

    def test_beta_rejects_modified_binary_before_creating_run(self):
        cache = self.beta_fixture()
        (cache / "qemu/qemu-system-x86_64").write_bytes(b"tampered")
        result = self.launch(REIMS_STACK="beta", REIMS_BETA_CACHE=str(cache))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hash mismatch", result.stderr)
        self.assertFalse((self.root / "vendor/reims-lab/runtime/current").exists())

    def test_stack_and_device_must_match(self):
        cache = self.beta_fixture()
        for variables in [{"REIMS_STACK": "unknown"}, {"REIMS_STACK": "beta", "REIMS_GFX_DEVICE": "reims-vgpu-pci"},
                          {"REIMS_STACK": "beta", "REIMS_RAM_BACKEND": "ram"}]:
            result = self.launch(REIMS_BETA_CACHE=str(cache), **variables)
            self.assertNotEqual(result.returncode, 0)

    def test_lab_refuses_to_overlap_the_normal_vm(self):
        with (self.root / "vendor/OSX-KVM/mac_hdd_ng.img.launch.lock").open("w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Stop the normal VM", result.stderr)
        self.assertFalse((self.root / "vendor/reims-lab/runtime/current").exists())

    def launch(self, **variables):
        return subprocess.run(["bash", str(self.root / "setup/72-boot-reims.sh")],
                              env=dict(self.env, **variables), capture_output=True, text=True)

    def arguments(self):
        current = self.root / "vendor/reims-lab/runtime/current"
        return json.loads((current / "qemu.log").read_text())

    def test_default_uses_verified_profile_and_independent_guest_overlay(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.arguments()
        self.assertIn(f"id=OpenCoreBoot,if=none,snapshot=on,format=qcow2,file={self.profile}/OpenCore.qcow2", args)
        self.assertIn("reboot=shutdown,shutdown=poweroff", args)
        self.assertIn("pci-bridge,chassis_nr=5,id=pci.5,bus=pcie.0,addr=1e.0", args)
        disk = next(value for value in args if value.startswith("id=MacHDD,"))
        self.assertIn("/runtime/run-", disk)
        self.assertNotIn("file=" + str(self.base / "macos-base.qcow2"), disk)
        self.assertEqual((self.base / "OVMF_VARS.fd").read_bytes(), b"fixture")

    def test_diagnostic_memory_and_shutdown_options_are_explicit(self):
        result = self.launch(REIMS_BOOT_PROFILE="base", REIMS_RAM_BACKEND="ram", REIMS_GDB="1", REIMS_SHUTDOWN_ACTION="pause")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.arguments()
        self.assertIn("memory-backend-ram,id=reims-ram,size=8192M,share=on", args)
        self.assertIn("reboot=shutdown,shutdown=pause", args)
        self.assertIn("-gdb", args)
        self.assertIn(f"id=OpenCoreBoot,if=none,snapshot=on,format=qcow2,file={self.base}/OpenCore.qcow2", args)

    def test_modified_profile_is_rejected_without_launch(self):
        (self.profile / "OpenCore.qcow2").write_bytes(b"unknown edit")
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hash mismatch", result.stderr)
        self.assertFalse((self.root / "vendor/reims-lab/runtime/current").exists())

    def test_editing_launcher_while_qemu_runs_does_not_break_teardown(self):
        started, release = self.root / "started", self.root / "release"
        qemu = self.root / "vendor/reims-vgpu/vendor/qemu/build/qemu-system-x86_64"
        qemu.write_text("#!/usr/bin/env python3\nfrom pathlib import Path\nimport time\n"
                        f"Path({str(started)!r}).touch()\n"
                        f"while not Path({str(release)!r}).exists(): time.sleep(.02)\n")
        launcher = self.root / "setup/72-boot-reims.sh"
        process = subprocess.Popen(["bash", str(launcher)], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(started.exists(), "QEMU fixture did not start")
            launcher.write_text("# Harmless source edit during a debug run\n" * 500 + launcher.read_text())
            release.touch()
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stdout + stderr)
        finally:
            release.touch()
            if process.poll() is None:
                process.kill()
                process.communicate()
