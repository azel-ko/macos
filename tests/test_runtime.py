import importlib.util
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("host_cpus", ROOT / "setup/host-cpus.py")
host_cpus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host_cpus)


class CpuSelectionTests(unittest.TestCase):
    def test_hybrid_keeps_fast_physical_cores_and_their_siblings(self):
        rows = [(c, c // 2, 4700) for c in range(8)]
        rows += [(c, c - 4, 3500) for c in range(8, 16)]
        self.assertEqual(host_cpus.select_cpus(rows, 4), list(range(8)))

    def test_fallback_when_allowed_fast_cores_are_insufficient(self):
        rows = [(0, 0, 4700), (1, 0, 4700), (8, 4, 3500), (9, 5, 3500)]
        self.assertEqual(host_cpus.select_cpus(rows, 4), [0, 1, 8, 9])

    def test_missing_frequency_does_not_exclude_cpus(self):
        rows = [(c, c, 0) for c in (2, 5, 9, 11)]
        self.assertEqual(host_cpus.select_cpus(rows, 4), [2, 5, 9, 11])


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ("setup", "conf", "bin", "vendor/OSX-KVM/OpenCore"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        for name in ("setup/40-boot-macos.sh", "conf/vm.env"):
            shutil.copy(ROOT / name, self.root / name)
        for name in ("OpenCore/OpenCore.qcow2", "OVMF_CODE_4M.fd", "OVMF_VARS_4M.macvm.fd", "mac_hdd_ng.img", "BaseSystem.img"):
            (self.root / "vendor/OSX-KVM" / name).touch()
        for name, size in (("OVMF_CODE_4M.fd", 3653632), ("OVMF_VARS_4M.macvm.fd", 540672)):
            with (self.root / "vendor/OSX-KVM" / name).open("wb") as firmware:
                firmware.truncate(size)
        stub = self.root / "bin/qemu-system-x86_64"
        stub.write_text("#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n")
        stub.chmod(0o755)
        info = self.root / "bin/qemu-img"
        info.write_text("#!/bin/sh\nexit 0\n")
        info.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.root}/bin:{os.environ['PATH']}", VM_CPU_AFFINITY="off", ALLOW_NO_IGNORE_MSRS="1")

    def run_launch(self, **env):
        return subprocess.run(["bash", str(self.root / "setup/40-boot-macos.sh")], env=dict(self.env, **env), text=True, capture_output=True)

    def test_desktop_uses_gl_and_safe_direct_io(self):
        result = self.run_launch(DISPLAY_MODE="gtk", ATTACH_INSTALL_MEDIA="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(result.stdout.splitlines()[-1])
        self.assertIn("gtk,gl=on,grab-on-hover=off", args)
        self.assertIn("ide-hd,bus=sata.4,drive=MacHDD,rotation_rate=1,discard_granularity=512", args)
        self.assertIn("id=MacHDD,if=none,file=mac_hdd_ng.img,format=qcow2,cache=none,aio=threads,discard=unmap", args)
        self.assertNotIn("ide-hd,bus=sata.3,drive=InstallMedia", args)
        self.assertIn("unix:/tmp/macvm-qmp.sock,server=on,wait=off", args)
        self.assertIn("usb-tablet,bus=xhci.0,id=tablet", args)
        self.assertIn("usb-kbd,bus=ehci.0", args)
        self.assertNotIn("usb-mouse,bus=ehci.0", args)

    def test_relative_mouse_fallback_omits_absolute_device(self):
        result = self.run_launch(VM_POINTER="mouse")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(result.stdout.splitlines()[-1])
        self.assertIn("usb-mouse,bus=ehci.0", args)
        self.assertFalse(any(arg.startswith("usb-tablet") for arg in args))

    def test_vnc_and_installer_remain_available(self):
        result = self.run_launch(DISPLAY_MODE="vnc", ATTACH_INSTALL_MEDIA="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(result.stdout.splitlines()[-1])
        self.assertIn("127.0.0.1:1", args)
        self.assertIn("ide-hd,bus=sata.3,drive=InstallMedia", args)

    def test_rejects_mixed_firmware_generations(self):
        old_vars = self.root / "vendor/OSX-KVM/old-vars.fd"
        with old_vars.open("wb") as firmware:
            firmware.truncate(131072)
        result = self.run_launch(OVMF_VARS="old-vars.fd")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CODE/VARS 尺寸不匹配", result.stdout)

    def test_initializes_private_variables_from_matching_template(self):
        disk_root = self.root / "vendor/OSX-KVM"
        target = disk_root / "OVMF_VARS_4M.macvm.fd"
        target.rename(disk_root / "template.fd")
        result = self.run_launch(OVMF_VARS_TEMPLATE=str(disk_root / "template.fd"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.stat().st_size, 540672)
        with target.open("r+b") as firmware:
            firmware.write(b"guest-variable")
        result = self.run_launch(OVMF_VARS_TEMPLATE=str(disk_root / "template.fd"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_bytes()[:14], b"guest-variable")

    def test_rejects_unsafe_cache_and_invalid_topology(self):
        for env in ({"VM_DISK_CACHE": "unsafe"}, {"VM_SMP": "6"}, {"DISPLAY_MODE": "typo"}, {"VM_POINTER": "typo"}):
            with self.subTest(env=env):
                self.assertNotEqual(self.run_launch(**env).returncode, 0)

    def test_disk_probe_failure_stops_before_qemu(self):
        (self.root / "bin/qemu-img").write_text("#!/bin/sh\nexit 1\n")
        result = self.run_launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("系统盘不可访问", result.stdout)

    def test_duplicate_launch_does_not_replace_control_sockets(self):
        lock_path = self.root / "vendor/OSX-KVM/mac_hdd_ng.img.launch.lock"
        with lock_path.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("已经在运行", result.stdout)


class GuestPreferencesTests(unittest.TestCase):
    def test_protected_restore_reports_pending_gui_and_restores_other_domains(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = root / "backup"
            backup.mkdir()
            for domain in ("NSGlobalDomain", "com.apple.universalaccess", "com.apple.finder", "com.apple.dock"):
                (backup / f"{domain}.plist").write_text("<plist/>")
            (root / "uname").write_text("#!/bin/sh\necho Darwin\n")
            (root / "killall").write_text("#!/bin/sh\nexit 0\n")
            (root / "defaults").write_text('#!/bin/sh\necho "$*" >> "$HOME/defaults-calls"\n[ "$2" != com.apple.universalaccess ]\n')
            for name in ("uname", "killall", "defaults"):
                (root / name).chmod(0o755)
            result = subprocess.run(
                ["bash", str(ROOT / "setup/60-optimize-guest.sh"), "--restore", str(backup)],
                env=dict(os.environ, HOME=tmp, PATH=f"{tmp}:{os.environ['PATH']}"),
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("辅助功能偏好受保护", result.stdout)
            self.assertIn("import com.apple.dock", (root / "defaults-calls").read_text())

    def test_protected_accessibility_domain_keeps_other_optimizations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "uname").write_text("#!/bin/sh\necho Darwin\n")
            (root / "killall").write_text("#!/bin/sh\nexit 0\n")
            (root / "defaults").write_text(
                '#!/bin/sh\n'
                'case "$1" in read) exit 1 ;; esac\n'
                'printf "%s\\n" "$*" >> "$HOME/defaults-calls"\n'
                '[ "$2" != com.apple.universalaccess ]\n'
            )
            for name in ("uname", "killall", "defaults"):
                (root / name).chmod(0o755)
            result = subprocess.run(
                ["bash", str(ROOT / "setup/60-optimize-guest.sh")],
                env=dict(os.environ, HOME=tmp, PATH=f"{tmp}:{os.environ['PATH']}"),
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("系统设置", result.stdout)
            calls = (root / "defaults-calls").read_text()
            self.assertIn("write com.apple.dock mineffect -string scale", calls)
            backups = list((root / "Library/Application Support/macos-kvm-tuning").glob("backup-*"))
            self.assertEqual(len(list(backups[0].glob("*.absent"))), 4)

    def test_incomplete_backup_does_not_partially_restore_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backup = root / "backup"
            backup.mkdir()
            (backup / "NSGlobalDomain.plist").write_text("<plist/>")
            (root / "uname").write_text("#!/bin/sh\necho Darwin\n")
            (root / "defaults").write_text('#!/bin/sh\necho called >> "$HOME/defaults-calls"\n')
            for name in ("uname", "defaults"):
                (root / name).chmod(0o755)
            result = subprocess.run(
                ["bash", str(ROOT / "setup/60-optimize-guest.sh"), "--restore", str(backup)],
                env=dict(os.environ, HOME=tmp, PATH=f"{tmp}:{os.environ['PATH']}"),
                text=True, capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("缺少备份", result.stdout)
            self.assertFalse((root / "defaults-calls").exists())


if __name__ == "__main__":
    unittest.main()
