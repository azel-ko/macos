import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reims_sources", ROOT / "setup/reims_sources.py")
sources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sources)


class SourcePatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "vendor/reims-vgpu"
        (self.root / "conf").mkdir()
        (self.root / "patches").mkdir()
        pins = {"local_patch": "patches/local.patch"}
        for path, key in [(self.source, "reims_vgpu"), (self.source / "vendor/qemu", "qemu")]:
            path.mkdir(parents=True)
            sources.git(path, "init", "-q")
            (path / "fixture.txt").write_text("original\n")
            sources.git(path, "add", "fixture.txt")
            sources.git(path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
            pins[key] = sources.git(path, "rev-parse", "HEAD").decode().strip()
        (self.source / "fixture.txt").write_text("patched\n")
        self.patch = self.root / "patches/local.patch"
        self.patch.write_bytes(sources.git(self.source, "diff", "HEAD", "--full-index", "--binary"))
        (self.source / "fixture.txt").write_text("original\n")
        (self.root / "conf/reims.lock").write_text(json.dumps(pins))

    def test_applies_exact_patch_once_and_recognizes_it(self):
        self.assertEqual(sources.prepare(self.root), "Project patch applied")
        self.assertEqual((self.source / "fixture.txt").read_text(), "patched\n")
        self.assertEqual(sources.prepare(self.root), "Project patch already applied")

    def test_unknown_work_is_preserved_and_refused(self):
        file = self.source / "fixture.txt"
        file.write_text("user work\n")
        with self.assertRaisesRegex(RuntimeError, "other tracked changes"):
            sources.prepare(self.root)
        self.assertEqual(file.read_text(), "user work\n")

    def test_unpinned_source_is_refused_before_patching(self):
        lock = self.root / "conf/reims.lock"
        pins = json.loads(lock.read_text())
        pins["qemu"] = "0" * 40
        lock.write_text(json.dumps(pins))
        with self.assertRaisesRegex(RuntimeError, "unpinned build"):
            sources.prepare(self.root)
        self.assertEqual((self.source / "fixture.txt").read_text(), "original\n")
