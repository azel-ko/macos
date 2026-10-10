#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/reims-env.sh"
cd "$REIMS_PROJECT_ROOT"
python3 setup/reims_sources.py
for tool in cargo rustc rustup llvm-dis spirv-val pkg-config; do
  command -v "$tool" >/dev/null || { echo "Missing local dependency: $tool" >&2; exit 1; }
done
python3 - <<'PY'
import json, subprocess
from pathlib import Path
expected = json.loads(Path('conf/reims.lock').read_text())['rust']
actual = subprocess.check_output(['rustc', '--version'], text=True).split()[1]
if actual != expected:
    raise SystemExit(f'Expected Rust {expected}, found {actual}; refusing an unpinned build')
PY
cd "$REIMS_PROJECT_ROOT/vendor/reims-vgpu/vendor/qemu"
if [ ! -f build/build.ninja ]; then
  ./configure --target-list=x86_64-softmmu --disable-hvf --disable-cocoa \
    --disable-docs --disable-bsd-user --disable-linux-user --disable-tools \
    -Dreims_vgpu_backend=vulkan
fi
ninja -C build -j "${REIMS_BUILD_JOBS:-2}" qemu-system-x86_64
bash "$REIMS_PROJECT_ROOT/vendor/reims-vgpu/crates/reims-vgpu-efi/scripts/reims-vgpu-efi-rom/reims-vgpu-efi-rom.sh"
./build/qemu-system-x86_64 -device reims-vgpu-pci,help >/dev/null
