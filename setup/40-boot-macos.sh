#!/usr/bin/env bash
# 40-boot-macos.sh —— 启动 macOS 虚拟机(软件渲染模式,无需 GPU 直通)
# 参数基于上游 OpenCore-Boot.sh(commit 见 vendor/LOCK),资源值来自 conf/vm.env
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source conf/vm.env

launcher=()
if [ "$VM_CPU_AFFINITY" != "off" ]; then
  if [ "$VM_CPU_AFFINITY" = "auto" ]; then
    VM_CPU_AFFINITY="$(python3 setup/host-cpus.py --min-cores "$VM_CORES")"
  fi
  taskset -c "$VM_CPU_AFFINITY" true || { echo "!! CPU 亲和性不可用: $VM_CPU_AFFINITY"; exit 1; }
  launcher=(taskset -c "$VM_CPU_AFFINITY")
fi

if [ "$VM_SMP" -ne "$((VM_CORES * VM_THREADS))" ]; then
  echo "!! VM_SMP 必须等于 VM_CORES * VM_THREADS"
  exit 1
fi
case "$DISPLAY_MODE" in gtk|vnc) ;; *) echo "!! DISPLAY_MODE 只能是 gtk 或 vnc"; exit 1 ;; esac
case "$DISPLAY_GL" in on|off) ;; *) echo "!! DISPLAY_GL 只能是 on 或 off"; exit 1 ;; esac
case "$VM_POINTER" in tablet|mouse) ;; *) echo "!! VM_POINTER 只能是 tablet 或 mouse"; exit 1 ;; esac
case "$VM_DISK_CACHE" in none|writeback|writethrough|directsync) ;; *) echo "!! 不支持的安全磁盘缓存模式: $VM_DISK_CACHE"; exit 1 ;; esac
case "$VM_DISK_AIO" in threads|native|io_uring) ;; *) echo "!! 不支持的 AIO 模式: $VM_DISK_AIO"; exit 1 ;; esac

available_mb=$(awk '/MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo)
if [ "$available_mb" -lt "$((VM_RAM_MB + 2048))" ]; then
  echo "!! 宿主机可用内存 ${available_mb}MB,分配 ${VM_RAM_MB}MB 后不足 2GB 余量,可能产生换页卡顿。"
fi

cd vendor/OSX-KVM

# OVMF 固件可用环境变量覆盖(排错用系统 OVMF 对比测试)
OVMF_CODE="${OVMF_CODE:-OVMF_CODE_4M.fd}"

for f in OpenCore/OpenCore.qcow2 "$OVMF_CODE" "$VM_DISK_FILE"; do
  [ -f "$f" ] || { echo "!! 缺少 $f —— 按顺序运行 setup/10、20、30 脚本"; exit 1; }
done

# 在 QEMU 创建控制 socket 前检查镜像锁,避免重复启动破坏正在运行的控制通道。
exec 9>"${VM_DISK_FILE}.launch.lock"
flock -n 9 || { echo "!! 这块系统盘的虚拟机已经在运行"; exit 1; }
qemu-img info "$VM_DISK_FILE" >/dev/null || { echo "!! 系统盘不可访问或正在被其他虚拟机使用"; exit 1; }

if [ -z "${OVMF_VARS:-}" ]; then
  OVMF_VARS=OVMF_VARS_4M.macvm.fd
  if [ ! -e "$OVMF_VARS" ]; then
    template="${OVMF_VARS_TEMPLATE:-/usr/share/OVMF/OVMF_VARS_4M.fd}"
    [ -f "$template" ] || { echo "!! 缺少 4MB 固件变量模板: $template"; exit 1; }
    cp -- "$template" "$OVMF_VARS"
  fi
fi
[ -f "$OVMF_VARS" ] || { echo "!! 缺少固件变量文件: $OVMF_VARS"; exit 1; }
firmware_pair="$(stat -c %s "$OVMF_CODE"),$(stat -c %s "$OVMF_VARS")"
case "$firmware_pair" in
  3653632,540672|1966080,131072) ;;
  *) echo "!! OVMF CODE/VARS 尺寸不匹配: $firmware_pair;请使用同一套 2MB 或 4MB 固件"; exit 1 ;;
esac

if [ "$(cat /sys/module/kvm/parameters/ignore_msrs 2>/dev/null)" != "Y" ] && [ "${ALLOW_NO_IGNORE_MSRS:-0}" != "1" ]; then
  echo "!! kvm ignore_msrs 未开启,macOS 会开机死循环。请先运行 setup/00-deps.sh"
  echo "   (排错实验可用 ALLOW_NO_IGNORE_MSRS=1 绕过)"
  exit 1
fi

MY_OPTIONS="${MY_OPTIONS:-+ssse3,+sse4.2,+popcnt,+avx,+aes,+xsave,+xsaveopt,check}"

args=(
  -enable-kvm -m "$VM_RAM_MB"
  # 13代酷睿(Raptor Lake)实测:Haswell-noTSX 会导致内核交接即崩溃,
  # 必须用 Skylake-Client(自带AVX2,Sonoma/Sequoia/Tahoe 均可)
  # 排错时可用 CPU_MODEL=host 或 Penryn 对比测试
  -cpu "${CPU_MODEL:-Skylake-Client,-hle,-rtm}",kvm=on,vendor=GenuineIntel,"${CPU_EXTRA:-+invtsc,vmware-cpuid-freq=on}","$MY_OPTIONS"
  -machine q35
  -smp "$VM_SMP",cores="$VM_CORES",threads="$VM_THREADS",sockets=1
  -device qemu-xhci,id=xhci
  # 保留 EHCI 键盘供固件/恢复环境使用。
  # Sonoma 的绝对定位 tablet 另挂 XHCI;不要同时启用相对 USB 鼠标,
  # 否则其后激活的输入处理器可能让 GTK 仍选择相对定位。
  -device usb-ehci,id=ehci
  -device usb-kbd,bus=ehci.0
  -device isa-applesmc,osk="ourhardworkbythesewordsguardedpleasedontsteal(c)AppleComputerInc"
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE"
  -drive if=pflash,format=raw,file="$OVMF_VARS"
  -smbios type=2
  -device ich9-intel-hda -device hda-duplex
  -device ich9-ahci,id=sata
  -drive id=OpenCoreBoot,if=none,snapshot=on,format=qcow2,file="OpenCore/OpenCore.qcow2"
  -device ide-hd,bus=sata.2,drive=OpenCoreBoot
  -drive "id=MacHDD,if=none,file=$VM_DISK_FILE,format=qcow2,cache=$VM_DISK_CACHE,aio=$VM_DISK_AIO,discard=unmap"
  -device ide-hd,bus=sata.4,drive=MacHDD,rotation_rate=1,discard_granularity=512
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:${SSH_HOST_PORT}-:22 -device virtio-net-pci,netdev=net0,id=net0,mac=52:54:00:c9:18:27
  # 备选:若虚拟机内拿不到网络,换 macOS 原生支持的 vmxnet3:
  # -netdev user,id=net0,hostfwd=tcp:127.0.0.1:${SSH_HOST_PORT}-:22 -device vmxnet3,netdev=net0,id=net0,mac=52:54:00:c9:18:27
  -monitor unix:/tmp/macvm-monitor.sock,server,nowait
  -qmp unix:/tmp/macvm-qmp.sock,server=on,wait=off
  -serial file:macos-serial.log    # XNU 内核日志(boot-args 含 serial=1 时生效)
  -device "vmware-svga,vgamem_mb=${VIDEO_RAM_MB:-64}"
)

if [ "$VM_POINTER" = "tablet" ]; then
  args+=(-device usb-tablet,bus=xhci.0,id=tablet)
else
  args+=(-device usb-mouse,bus=ehci.0)
fi

# 显示模式:vnc = 无头运行(关闭查看器不会杀死虚拟机),gtk = 原生窗口
if [ "${DISPLAY_MODE:-gtk}" = "vnc" ]; then
  args+=(-display none -vnc "127.0.0.1:${VNC_DISPLAY:-1}")
  display_hint="VNC 127.0.0.1:$((5900 + ${VNC_DISPLAY:-1}))"
else
  args+=(-display "gtk,gl=$DISPLAY_GL,grab-on-hover=off")
  display_hint="本地 GTK 窗口"
fi

# 调试:panic 时定格画面而不是重启循环(用于观察崩溃信息)
[ "${DEBUG_NO_REBOOT:-0}" = "1" ] && args+=(-no-reboot)

# 安装介质存在才挂载;装完系统删除 BaseSystem.img 后即自动跳过
if [ "$ATTACH_INSTALL_MEDIA" = "1" ] && [ -f BaseSystem.img ]; then
  args+=(
    -device ide-hd,bus=sata.3,drive=InstallMedia
    -drive id=InstallMedia,if=none,file="BaseSystem.img",format=raw
  )
fi

echo ">>> 启动 $VM_NAME(RAM ${VM_RAM_MB}MB / ${VM_SMP} vCPU / VRAM ${VIDEO_RAM_MB:-64}MB),显示: $display_hint"
echo ">>> CPU 范围: $VM_CPU_AFFINITY; 磁盘: cache=$VM_DISK_CACHE / aio=$VM_DISK_AIO / TRIM"
echo ">>> 鼠标: $VM_POINTER"
exec "${launcher[@]}" qemu-system-x86_64 "${args[@]}"
