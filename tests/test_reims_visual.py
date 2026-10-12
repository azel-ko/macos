from pathlib import Path
import sys
import unittest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))
from reims_visual import palette_evidence, display_window, editor_target, ide_file_opened


class PaletteTests(unittest.TestCase):
    def test_file_open_accepts_lightedit_startup_and_rejects_before_open_or_another_file(self):
        name = "reims-ide-unique.txt"
        self.assertTrue(ide_file_opened("INFO - fileOpened " + name, name))
        self.assertTrue(ide_file_opened("INFO - Opened new tab for /Users/azel/" + name, name))
        self.assertFalse(ide_file_opened("INFO - beforeFileOpened " + name, name))
        self.assertFalse(ide_file_opened("INFO - fileOpened " + name + "-other", name))
        self.assertFalse(ide_file_opened("INFO - fileOpened reims-ide-other.txt", name))

    def test_editor_input_requires_one_large_window_without_a_dialog(self):
        report = {"screen": [1920,1080], "windows": [{"bounds": {"X": 260, "Y": 45, "Width": 1400, "Height": 930}}]}
        x, y = editor_target(report)
        self.assertAlmostEqual(x / 32767 * 1920, 960, delta=.1)
        self.assertAlmostEqual(y / 32767 * 1080, 417, delta=.1)
        report["windows"].append({"bounds": {"X": 700, "Y": 400, "Width": 350, "Height": 200}})
        with self.assertRaisesRegex(RuntimeError, "Close IntelliJ dialogs"):
            editor_target(report)

    def test_capture_targets_exact_pid_and_accepts_beta_capture_title(self):
        rows = ["0x1 0 99 host Reims vGPU", "0x2 0 42 host Reims vGPU (port 1) — input captured (press Ctrl+Alt+Super to release)",
                "0x3 0 42 host unrelated application"]
        self.assertEqual(display_window(rows, 42), "0x2")
        with self.assertRaises(RuntimeError):
            display_window(rows, 100)
        with self.assertRaises(RuntimeError):
            display_window(rows + ["0x4 0 42 host Reims vGPU"], 42)

    def fixture(self):
        image = Image.new("RGB", (120, 80), "black")
        samples = []
        for n, color in enumerate([(255,0,0), (0,255,0), (0,0,255), (0,255,255), (255,0,255), (255,255,0)]):
            x, y = 10 + n * 15, 40
            image.putpixel((x, y), color)
            samples.append({"x": x, "y": 30, "rgb": color})
        # A 120x60 guest, centered in a 120x80 host capture.
        return image, {"screen": [120, 60], "samples": samples}

    def test_letterbox_offsets_are_applied(self):
        image, report = self.fixture()
        self.assertTrue(palette_evidence(image, report)["pass"])

    def test_black_corruption_one_wrong_color_and_missing_samples_fail(self):
        image, report = self.fixture()
        image.putpixel((10, 40), (0, 0, 0))
        self.assertFalse(palette_evidence(image, report)["pass"])
        self.assertFalse(palette_evidence(Image.new("RGB", image.size), report)["pass"])
        report["samples"].pop()
        with self.assertRaises(ValueError):
            palette_evidence(image, report)
