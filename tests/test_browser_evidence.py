import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("browser_stress", ROOT / "setup/77-browser-stress.py")
browser = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(ROOT / "setup"))
try:
    spec.loader.exec_module(browser)
finally:
    sys.path.pop(0)


class BrowserEvidenceTests(unittest.TestCase):
    def reports(self):
        return [{"webglPass": True, "elapsedSeconds": n, "host_monotonic": 100+n, "frames": n*60}
                for n in range(2, 61, 2)]

    def test_healthy_continuous_run_passes(self):
        self.assertTrue(browser.browser_evidence(self.reports(), 60))

    def test_early_success_does_not_hide_a_stalled_or_restarted_browser(self):
        reports = self.reports()
        self.assertFalse(browser.browser_evidence(reports[:10], 60))
        reports[15]["frames"] = 0
        self.assertFalse(browser.browser_evidence(reports, 60))
        reports = self.reports()
        del reports[10:17]
        self.assertFalse(browser.browser_evidence(reports, 60))

    def test_one_wrong_pixel_or_malformed_report_fails(self):
        reports = self.reports()
        reports[10]["webglPass"] = False
        self.assertFalse(browser.browser_evidence(reports, 60))
        reports[10] = {"webglPass": True}
        self.assertFalse(browser.browser_evidence(reports, 60))

    def test_dead_guest_health_is_recorded_instead_of_raising(self):
        with patch.object(browser.subprocess, "run", side_effect=subprocess.TimeoutExpired("ssh", 8)):
            with patch.object(browser, "QMP", side_effect=FileNotFoundError("socket gone")):
                result = browser.sample_guest(["ssh"], Path("missing.sock"))
        self.assertFalse(result["ssh_ok"])
        self.assertEqual(result["status"]["status"], "unavailable")
