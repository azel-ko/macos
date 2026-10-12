import sys
import json
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))
from reims_diagnostics import own_gpu_hangs, retained_pid, vulkan_summary


class DiagnosticsTests(unittest.TestCase):
    def test_clean_exit_uses_only_the_same_runs_recorded_pid(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder) / "run-test"
            run.mkdir()
            self.assertIsNone(retained_pid(run))
            record = run / "gpu-diagnostics.json"
            record.write_text(json.dumps({"run": run.name, "qemu_pid": 42}))
            self.assertEqual(retained_pid(run), 42)
            record.write_text(json.dumps({"run": "run-other", "qemu_pid": 42}))
            self.assertIsNone(retained_pid(run))
            (run / "qemu.pid").write_text("99\n")
            self.assertEqual(retained_pid(run), 99)

    def test_vulkan_errors_keep_identifiers_without_shader_text(self):
        result = vulkan_summary([
            "ERROR VUID-VkWriteDescriptorSet-descriptorType-00319 shader private bytes\n",
            "ERROR VUID-VkWriteDescriptorSet-descriptorType-00319\n",
            "reims-vgpu: fatal: the Vulkan device was lost\n",
        ])
        self.assertEqual(result["validation_ids"], {"VUID-VkWriteDescriptorSet-descriptorType-00319": 2})
        self.assertEqual(result["device_lost_lines"], 1)
        self.assertEqual(result["fatal_lines"], 1)
        self.assertNotIn("private", str(result))

    def test_gpu_hangs_require_this_qemu_pid_not_a_prefix_or_another_process(self):
        entries = [{"MESSAGE": message, "__REALTIME_TIMESTAMP": "123"} for message in [
            "i915 GPU HANG: ecode 12:1:859ffffb, in qemu-system-x86 [42]",
            "i915 GPU HANG: ecode 12:1:859ffffb, in qemu-system-x86 [420]",
            "i915 GPU HANG: ecode 12:1:859ffffb, in firefox [42]",
            "qemu-system-x86 [42] initialized",
        ]]
        self.assertEqual(own_gpu_hangs(entries, 42),
                         [{"journal_realtime_us": "123", "ecode": "12:1:859ffffb"}])
