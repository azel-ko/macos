#!/usr/bin/env python3
"""Validate pinned Reims sources and apply the project's reproducible patch."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(path, *arguments):
    return subprocess.run(["git", "-C", str(path), *arguments], check=True,
                          capture_output=True).stdout


def apply_project_patch(source, patch):
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


def prepare(root=ROOT, pin_file="conf/reims.lock", source_dir="vendor/reims-vgpu"):
    pins = json.loads((root / pin_file).read_text())
    source = root / source_dir
    for path, key in [(source, "reims_vgpu"), (source / "vendor/qemu", "qemu")]:
        actual = git(path, "rev-parse", "HEAD").decode().strip()
        if actual != pins[key]:
            raise RuntimeError(f"{path}: expected {pins[key]}, found {actual}; refusing unpinned build")
    return apply_project_patch(source, root / pins["local_patch"])


def prepare_translator(root, pins):
    source = root / "vendor/metal2vulkan-beta"
    actual = git(source, "rev-parse", "HEAD").decode().strip()
    if actual != pins["metal2vulkan"]:
        raise RuntimeError(f"Unpinned metal2vulkan source: {actual}")
    return apply_project_patch(source, root / pins["metal2vulkan_patch"])


if __name__ == "__main__":
    print(prepare())
