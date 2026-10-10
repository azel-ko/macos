#!/usr/bin/env python3
"""Validate pinned Reims sources and apply the project's reproducible patch."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(path, *arguments):
    return subprocess.run(["git", "-C", str(path), *arguments], check=True,
                          capture_output=True).stdout


def prepare(root=ROOT):
    pins = json.loads((root / "conf/reims.lock").read_text())
    source = root / "vendor/reims-vgpu"
    for path, key in [(source, "reims_vgpu"), (source / "vendor/qemu", "qemu")]:
        actual = git(path, "rev-parse", "HEAD").decode().strip()
        if actual != pins[key]:
            raise RuntimeError(f"{path}: expected {pins[key]}, found {actual}; refusing unpinned build")
    patch = root / pins["local_patch"]
    expected = patch.read_bytes()
    if not expected:
        raise RuntimeError("Empty Reims source patch")
    changes = git(source, "diff", "HEAD", "--full-index", "--binary")
    if changes == expected:
        return "Project patch already applied"
    if changes:
        raise RuntimeError("Reims has other tracked changes; preserve and review them before building")
    git(source, "apply", "--check", str(patch))
    git(source, "apply", str(patch))
    if git(source, "diff", "HEAD", "--full-index", "--binary") != expected:
        raise RuntimeError("Applied source differs from the declared patch")
    return "Project patch applied"


if __name__ == "__main__":
    print(prepare())
