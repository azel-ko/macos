#!/usr/bin/env bash
# GPU-touching owner regressions run serially, with VM boots held off.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/reims-beta-env.sh"
source "$REIMS_PROJECT_ROOT/conf/vm.env"
mkdir -p "$REIMS_LAB_ROOT/runtime"
exec 9>"$REIMS_LAB_ROOT/runtime/launch.lock"
flock -n 9 || { echo "Stop the lab VM before running GPU tests" >&2; exit 1; }
exec 8>"$REIMS_PROJECT_ROOT/vendor/OSX-KVM/${VM_DISK_FILE}.launch.lock"
flock -n 8 || { echo "Stop the normal VM before running GPU tests" >&2; exit 1; }
cd "$REIMS_PROJECT_ROOT"
python3 - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, 'setup')
from reims_sources import prepare_translator
prepare_translator(Path.cwd(), json.loads(Path('conf/reims-beta.lock').read_text()))
PY
export CARGO_TARGET_DIR="$REIMS_BETA_CACHE/probe-target"
export RUSTFLAGS="${RUSTFLAGS:-} --cfg m2v_gpu -Dwarnings"
cd "$REIMS_PROJECT_ROOT/vendor/metal2vulkan-beta"
cargo test --release -p metal2vulkan-runtime --lib local_intel_tests -- --test-threads=1
cargo test --release -p metal2vulkan-runtime --lib iris_xe_mesa_25_2_8_multisampled_depth_upload -- --nocapture --test-threads=1
cargo test --release -p metal2vulkan-runtime --lib a_blit_between_a_buffer_and_a_multisampled_texture_round_trips_per_sample -- --nocapture --test-threads=1
