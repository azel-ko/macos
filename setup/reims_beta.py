"""Verify that a Beta binary and its ROM belong to the declared pinned build."""
import hashlib
import json
from pathlib import Path


def repair_local_sysroot(sysroot, host_lib=Path("/usr/lib/x86_64-linux-gnu")):
    """Relocate extracted pkg-config files; reuse installed runtime libraries."""
    if not sysroot.exists():
        return
    for pc in sysroot.rglob("*.pc"):
        lines = pc.read_text().splitlines(keepends=True)
        data = "".join(f"prefix={sysroot / 'usr'}\n" if line.rstrip() == "prefix=/usr" else line for line in lines)
        if data != "".join(lines):
            pc.write_text(data)
    folder = sysroot / "usr/lib/x86_64-linux-gnu"
    if not folder.exists():
        return
    for path in list(folder.iterdir()):
        if path.is_symlink() and not path.exists():
            target = path.readlink()
            if len(target.parts) == 1 and not target.is_absolute() and (host_lib / target).is_file():
                destination = folder / target
                if not destination.exists() and not destination.is_symlink():
                    destination.symlink_to(host_lib / target)


def verified_build(root, lab, cache):
    pins = json.loads((root / "conf/reims-beta.lock").read_text())
    manifest = json.loads((lab / "beta-dist/build-manifest.json").read_text())
    qemu = cache / "qemu/qemu-system-x86_64"
    rom = lab / "beta-dist/share/reims-vgpu/ReimsVgpu.rom"
    if manifest["source_pins"] != pins:
        raise RuntimeError("Beta build source pins differ; rebuild before launching")
    if "local_patch" in pins and manifest["source_patch_sha256"] != hashlib.sha256((root / pins["local_patch"]).read_bytes()).hexdigest():
        raise RuntimeError("Beta source patch hash mismatch; rebuild before launching")
    if "metal2vulkan_patch" in pins and manifest["metal2vulkan_patch_sha256"] != hashlib.sha256((root / pins["metal2vulkan_patch"]).read_bytes()).hexdigest():
        raise RuntimeError("Beta translator patch hash mismatch; rebuild before launching")
    for name, path in [("qemu", qemu), ("rom", rom)]:
        if Path(manifest[name]) != path or hashlib.sha256(path.read_bytes()).hexdigest() != manifest[name + "_sha256"]:
            raise RuntimeError(f"Beta {name} path or hash mismatch; refusing unverified build")
    return manifest
