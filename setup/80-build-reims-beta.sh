#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/reims-beta-env.sh"
cd "$REIMS_PROJECT_ROOT"
python3 - <<'PY'
import json, os, subprocess, sys, tomllib
from pathlib import Path
root = Path(os.environ['REIMS_PROJECT_ROOT'])
source = Path(os.environ['REIMS_BETA_SOURCE'])
pins = json.loads((root / 'conf/reims-beta.lock').read_text())
sys.path.insert(0, str(root / 'setup'))
from reims_sources import prepare, prepare_translator
from reims_beta import repair_local_sysroot
prepare(root, 'conf/reims-beta.lock', 'vendor/reims-vgpu-beta')
prepare_translator(root, pins)
repair_local_sysroot(Path(os.environ['REIMS_LAB_ROOT']) / 'tools/sysroot-beta')
if subprocess.check_output(['git', '-C', str(source / 'vendor/qemu'), 'diff', 'HEAD', '--'], text=True):
    raise SystemExit('Tracked QEMU changes; refusing unrecorded build')
dependencies = tomllib.loads((source / 'Cargo.toml').read_text())['workspace']['dependencies']
for name in ['metal2vulkan', 'metal2vulkan-runtime']:
    if dependencies[name] != {'path': f'../metal2vulkan-beta/crates/{name}'}:
        raise SystemExit(f'Unexpected dependency route: {name}')
actual = subprocess.check_output(['rustc', '--version'], text=True).split()[1]
if actual != pins['rust']:
    raise SystemExit(f'Expected Rust {pins["rust"]}, found {actual}')
PY
for tool in clang lld-link ld.lld cmake ninja pkg-config; do
  command -v "$tool" >/dev/null || { echo "Missing Beta build dependency: $tool" >&2; exit 1; }
done
mkdir -p "$REIMS_BETA_CACHE/qemu"
cd "$REIMS_BETA_SOURCE"
cargo xtask dist --out "$REIMS_LAB_ROOT/beta-dist"
export PKG_CONFIG_PATH="$REIMS_LAB_ROOT/beta-dist/lib/pkgconfig:$PKG_CONFIG_PATH"
cd "$REIMS_BETA_CACHE/qemu"
configure_args=(--target-list=x86_64-softmmu --enable-kvm --enable-pvg --enable-slirp
  --disable-sdl --disable-gtk --disable-docs --disable-bsd-user --disable-linux-user
  --disable-tools --disable-containers)
signature="$(python3 - "${configure_args[@]}" <<'PY'
import hashlib, json, os, sys
from pathlib import Path
values = {key: os.environ.get(key) for key in ['REIMS_BETA_SOURCE', 'PKG_CONFIG_PATH', 'CFLAGS', 'LDFLAGS']}
values['arguments'] = sys.argv[1:]
values['pkgconfig'] = (Path(os.environ['REIMS_LAB_ROOT']) / 'beta-dist/lib/pkgconfig/reims-vgpu.pc').read_text()
print(hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest())
PY
)"
if [ ! -f build.ninja ] || [ "$(cat build-config.sha256 2>/dev/null || true)" != "$signature" ]; then
  "$REIMS_BETA_SOURCE/vendor/qemu/configure" "${configure_args[@]}"
  printf '%s\n' "$signature" > build-config.sha256
fi
ninja -j "${REIMS_BUILD_JOBS:-2}" qemu-system-x86_64
./qemu-system-x86_64 -device apple-gfx-pci,help >/dev/null
python3 - <<'PY'
import hashlib, json, os
from pathlib import Path
root = Path(os.environ['REIMS_PROJECT_ROOT'])
lab = Path(os.environ['REIMS_LAB_ROOT'])
cache = Path(os.environ['REIMS_BETA_CACHE'])
qemu = cache / 'qemu/qemu-system-x86_64'
rom = lab / 'beta-dist/share/reims-vgpu/ReimsVgpu.rom'
pins = json.loads((root / 'conf/reims-beta.lock').read_text())
manifest = {'source_pins': pins,
            'source_patch_sha256': hashlib.sha256((root / pins['local_patch']).read_bytes()).hexdigest(),
            'metal2vulkan_patch_sha256': hashlib.sha256((root / pins['metal2vulkan_patch']).read_bytes()).hexdigest(),
            'qemu': str(qemu), 'rom': str(rom),
            'qemu_sha256': hashlib.sha256(qemu.read_bytes()).hexdigest(),
            'rom_sha256': hashlib.sha256(rom.read_bytes()).hexdigest()}
(lab / 'beta-dist/build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
PY
