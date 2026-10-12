#!/usr/bin/env bash
# Boot the existing Sonoma installation through an independent writable overlay.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/reims-env.sh"
stack="${REIMS_STACK:-legacy}"
case "$stack" in
  legacy) ;;
  beta) source "$REIMS_PROJECT_ROOT/setup/reims-beta-env.sh" ;;
  *) echo "REIMS_STACK must be legacy or beta" >&2; exit 1 ;;
esac
source "$REIMS_PROJECT_ROOT/conf/vm.env"
base="$REIMS_LAB_ROOT/base"
qemu="$REIMS_PROJECT_ROOT/vendor/reims-vgpu/vendor/qemu/build/qemu-system-x86_64"
rom="$REIMS_PROJECT_ROOT/vendor/reims-vgpu/crates/reims-vgpu-efi/out/reims-vgpu-gop.rom"
if [ "$stack" = beta ]; then
  python3 - "$REIMS_PROJECT_ROOT" "$REIMS_LAB_ROOT" "$REIMS_BETA_CACHE" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'setup'))
from reims_beta import verified_build
try:
    verified_build(*(Path(value) for value in sys.argv[1:]))
except (OSError, KeyError, ValueError, RuntimeError) as error:
    raise SystemExit(f'Beta build verification failed: {error}; run setup/80-build-reims-beta.sh')
PY
  qemu="$REIMS_BETA_CACHE/qemu/qemu-system-x86_64"
  rom="$REIMS_LAB_ROOT/beta-dist/share/reims-vgpu/ReimsVgpu.rom"
fi
for file in "$base/manifest.json" "$base/macos-base.qcow2" "$base/OVMF_VARS.fd" "$base/OVMF_CODE.fd" "$base/OpenCore.qcow2" "$qemu" "$rom"; do
  [ -f "$file" ] || { echo "Missing: $file" >&2; exit 1; }
done
port="${REIMS_SSH_PORT:-2223}"
if [ "$stack" = beta ]; then default_graphics=apple-gfx-pci; else default_graphics=reims-vgpu-pci; fi
graphics="${REIMS_GFX_DEVICE:-$default_graphics}"
ram_backend="${REIMS_RAM_BACKEND:-memfd}"
shutdown_action="${REIMS_SHUTDOWN_ACTION:-poweroff}"
debugger="${REIMS_GDB:-0}"
boot_profile="${REIMS_BOOT_PROFILE:-osx-kvm-memory}"
case "$stack/$graphics" in legacy/reims-vgpu-pci|legacy/vmware-svga|beta/apple-gfx-pci) ;; *) echo "Unsupported REIMS_STACK/REIMS_GFX_DEVICE combination" >&2; exit 1 ;; esac
case "$ram_backend" in memfd|ram) ;; *) echo "Unsupported REIMS_RAM_BACKEND" >&2; exit 1 ;; esac
if [ "$stack" = beta ] && [ "$ram_backend" != memfd ]; then
  echo "Beta on Linux requires file-backed shared memfd RAM" >&2; exit 1
fi
case "$shutdown_action" in poweroff|pause) ;; *) echo "Unsupported REIMS_SHUTDOWN_ACTION" >&2; exit 1 ;; esac
case "$debugger" in 0|1) ;; *) echo "REIMS_GDB must be 0 or 1" >&2; exit 1 ;; esac
case "$boot_profile" in osx-kvm-memory|base) ;; *) echo "Unsupported REIMS_BOOT_PROFILE" >&2; exit 1 ;; esac
[[ "$port" =~ ^[0-9]+$ ]] && [ "$port" -ge 1024 ] && [ "$port" -le 65535 ] || {
  echo "REIMS_SSH_PORT must be 1024..65535" >&2; exit 1;
}
mkdir -p "$REIMS_LAB_ROOT/runtime"
exec 9>"$REIMS_LAB_ROOT/runtime/launch.lock"
flock -n 9 || { echo "A Reims test is already running" >&2; exit 1; }
exec 8>"$REIMS_PROJECT_ROOT/vendor/OSX-KVM/${VM_DISK_FILE}.launch.lock"
flock -n 8 || { echo "Stop the normal VM before running the GPU lab" >&2; exit 1; }
if [ -n "${REIMS_OPENCORE_FILE:-}" ]; then
  opencore="$(realpath "$REIMS_OPENCORE_FILE")"
elif [ "$boot_profile" = osx-kvm-memory ]; then
  opencore="$(python3 "$REIMS_PROJECT_ROOT/setup/75-opencore-profile.py" \
    --source "$base/OpenCore.qcow2" --output "$REIMS_LAB_ROOT/profiles/osx-kvm-memory" \
    --memory-profile "$REIMS_PROJECT_ROOT/conf/reims-opencore.json" --ensure)"
else
  opencore="$base/OpenCore.qcow2"
fi
[ -f "$opencore" ] || { echo "Missing OpenCore profile" >&2; exit 1; }
run="$(mktemp -d "$REIMS_LAB_ROOT/runtime/run-XXXXXXXX")"
qemu-img create -q -f qcow2 -F qcow2 -b "$base/macos-base.qcow2" "$run/macos.qcow2"
cp -- "$base/OVMF_VARS.fd" "$run/OVMF_VARS.fd"
chmod u+w "$run/OVMF_VARS.fd"
ln -sfn "$run" "$REIMS_LAB_ROOT/runtime/current"
if [ "$stack" = legacy ] && [ -f /tmp/reims-vgpu-fail.log ]; then
  cp -- /tmp/reims-vgpu-fail.log "$run/previous-device.log"
  : > /tmp/reims-vgpu-fail.log
fi
trap 'if [ "$stack" = legacy ] && [ -f /tmp/reims-vgpu-fail.log ]; then cp -- /tmp/reims-vgpu-fail.log "$run/device.log"; fi' EXIT

launcher=()
if [ "$VM_CPU_AFFINITY" != off ]; then
  if [ "$VM_CPU_AFFINITY" = auto ]; then
    VM_CPU_AFFINITY="$(python3 "$REIMS_PROJECT_ROOT/setup/host-cpus.py" --min-cores "$VM_CORES")"
  fi
  launcher=(taskset -c "$VM_CPU_AFFINITY")
fi
# Start with the copying path; host-pointer import is an optional optimization.
if [ "$stack" = legacy ]; then
  export REIMS_VGPU_GUEST_IMPORT="${REIMS_VGPU_GUEST_IMPORT:-off}"
else
  # The rewrite has its own memory owner; Alpha-only knobs do not apply.
  unset REIMS_VGPU_GUEST_IMPORT REIMS_VGPU_CACHED_VIEWS REIMS_VGPU_LAZY_WRITEBACK
fi
export REIMS_VGPU_WINDOW="${REIMS_VGPU_WINDOW:-1}"
args=(
  -enable-kvm -m "$VM_RAM_MB"
  -object "memory-backend-${ram_backend},id=reims-ram,size=${VM_RAM_MB}M,share=on"
  -machine pc-q35-8.2,memory-backend=reims-ram
  -cpu 'Skylake-Client,-hle,-rtm,kvm=on,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on,+ssse3,+sse4.2,+popcnt,+avx,+aes,+xsave,+xsaveopt,check'
  -smp "$VM_SMP",cores="$VM_CORES",threads="$VM_THREADS",sockets=1
  -device qemu-xhci,id=xhci -device usb-ehci,id=ehci
  -device usb-kbd,bus=ehci.0 -device usb-tablet,bus=xhci.0
  -device 'isa-applesmc,osk=ourhardworkbythesewordsguardedpleasedontsteal(c)AppleComputerInc'
  -drive "if=pflash,format=raw,readonly=on,file=$base/OVMF_CODE.fd"
  -drive "if=pflash,format=raw,file=$run/OVMF_VARS.fd"
  -smbios type=2 -device ich9-intel-hda -device hda-duplex
  -device ich9-ahci,id=sata
  -drive "id=OpenCoreBoot,if=none,snapshot=on,format=qcow2,file=$opencore"
  -device ide-hd,bus=sata.2,drive=OpenCoreBoot
  -drive "id=MacHDD,if=none,format=qcow2,file=$run/macos.qcow2,cache=none,aio=threads,discard=unmap"
  -device ide-hd,bus=sata.4,drive=MacHDD,rotation_rate=1
  -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:${port}-:22"
  -device virtio-net-pci,netdev=net0,id=net0,mac=52:54:00:c9:18:28
  -qmp "unix:$run/qmp.sock,server=on,wait=off"
  -monitor "unix:$run/monitor.sock,server=on,wait=off"
  -serial "file:$run/serial.log" -pidfile "$run/qemu.pid"
  -action "reboot=shutdown,shutdown=$shutdown_action" -vga none
)
if [ "$graphics" != vmware-svga ]; then
  if [ "$stack" = beta ]; then gpu_options=",resolution=1920x1080"; else gpu_options=",rombar=1"; fi
  args+=(
    -device pci-bridge,chassis_nr=5,id=pci.5,bus=pcie.0,addr=1e.0
    -device "$graphics,id=reimsvgpu,bus=pci.5,addr=00.0,romfile=$rom$gpu_options"
    -display none
  )
else
  unset REIMS_VGPU_WINDOW
  args+=(-device vmware-svga,vgamem_mb=64 -display gtk,gl=on,grab-on-hover=off)
fi
if [ "$debugger" = 1 ]; then
  args+=(-gdb "unix:$run/gdb.sock,server=on,wait=off")
fi
printf 'Run: %s\nSSH: ssh -p %s azel@127.0.0.1\n' "$run" "$port"
printf '%s\n' "$port" > "$run/ssh-port"
printf '%s\n' "$graphics" > "$run/graphics-device"
python3 - "$run" "$graphics" "$ram_backend" "$shutdown_action" "$debugger" "$opencore" "$stack" "$qemu" "$rom" <<'PY'
import hashlib, json, os, sys
from pathlib import Path
run, graphics, ram, shutdown, debugger, opencore, stack, qemu, rom = sys.argv[1:]
root = Path(os.environ['REIMS_LAB_ROOT']).parent.parent
pins = json.loads((root / ('conf/reims-beta.lock' if stack == 'beta' else 'conf/reims.lock')).read_text())
config = {
    'stack': stack,
    'graphics_device': graphics, 'ram_backend': ram, 'shutdown_action': shutdown,
    'gdb_enabled': debugger == '1',
    'opencore_sha256': hashlib.sha256(Path(opencore).read_bytes()).hexdigest(),
    'switches': {key: value for key, value in os.environ.items()
                 if key.startswith('REIMS_VGPU_')},
    'vulkan_diagnostics': {key: os.environ[key] for key in
                           ['VK_INSTANCE_LAYERS', 'VK_LAYER_PATH'] if key in os.environ},
    'source_pins': pins,
    'source_patch_sha256': hashlib.sha256((root / pins['local_patch']).read_bytes()).hexdigest() if 'local_patch' in pins else None,
    'metal2vulkan_patch_sha256': hashlib.sha256((root / pins['metal2vulkan_patch']).read_bytes()).hexdigest() if 'metal2vulkan_patch' in pins else None,
    'qemu_sha256': hashlib.sha256(Path(qemu).read_bytes()).hexdigest(),
    'rom_sha256': hashlib.sha256(Path(rom).read_bytes()).hexdigest(),
}
Path(run, 'config.json').write_text(json.dumps(config, indent=2) + '\n')
PY
# Finish inside one parsed block so source edits during a long QEMU run cannot
# resume Bash at a stale file offset. The EXIT trap still preserves evidence.
{
  "${launcher[@]}" "$qemu" "${args[@]}" > "$run/qemu.log" 2>&1
  exit "$?"
}
