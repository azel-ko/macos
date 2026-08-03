#!/usr/bin/env bash
# 40-boot-macos.sh —— 启动 macOS 虚拟机(软件渲染模式,无需 GPU 直通)
# 参数基于上游 OpenCore-Boot.sh(commit 见 vendor/LOCK),资源值来自 conf/vm.env
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source conf/vm.env

cd vendor/OSX-KVM

# OVMF 固件可用环境变量覆盖(排错用系统 OVMF 对比测试)
OVMF_CODE="${OVMF_CODE:-OVMF_CODE_4M.fd}"
OVMF_VARS="${OVMF_VARS:-OVMF_VARS-1920x1080.fd}"

for f in OpenCore/OpenCore.qcow2 "$OVMF_CODE" "$OVMF_VARS" "$VM_DISK_FILE"; do
  [ -f "$f" ] || { echo "!! 缺少 $f —— 按顺序运行 setup/10、20、30 脚本"; exit 1; }
done

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
  # 键鼠必须挂 EHCI:OVMF/OpenCore 引导菜单没有 XHCI 驱动,
  # 挂 xhci 会导致安装前阶段键鼠全部失灵( xhci 控制器保留给 macOS 用)
  # 注意必须用 usb-mouse 而非 usb-tablet:tablet 在 HID 描述符里是数字化仪,
  # macOS 会把它当绘图板(不驱动光标),mouse 才是标准鼠标
  # 代价:相对坐标,VNC 查看器里需抓取鼠标(Ctrl+Alt 释放)
  -device usb-ehci,id=ehci
  -device usb-kbd,bus=ehci.0 -device usb-mouse,bus=ehci.0
  -device isa-applesmc,osk="ourhardworkbythesewordsguardedpleasedontsteal(c)AppleComputerInc"
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE"
  -drive if=pflash,format=raw,file="$OVMF_VARS"
  -smbios type=2
  -device ich9-intel-hda -device hda-duplex
  -device ich9-ahci,id=sata
  -drive id=OpenCoreBoot,if=none,snapshot=on,format=qcow2,file="OpenCore/OpenCore.qcow2"
  -device ide-hd,bus=sata.2,drive=OpenCoreBoot
  -drive id=MacHDD,if=none,file="$VM_DISK_FILE",format=qcow2
  -device ide-hd,bus=sata.4,drive=MacHDD
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:${SSH_HOST_PORT}-:22 -device virtio-net-pci,netdev=net0,id=net0,mac=52:54:00:c9:18:27
  # 备选:若虚拟机内拿不到网络,换 macOS 原生支持的 vmxnet3:
  # -netdev user,id=net0,hostfwd=tcp:127.0.0.1:${SSH_HOST_PORT}-:22 -device vmxnet3,netdev=net0,id=net0,mac=52:54:00:c9:18:27
  -monitor unix:/tmp/macvm-monitor.sock,server,nowait
  -serial file:macos-serial.log    # XNU 内核日志(boot-args 含 serial=1 时生效)
  -device "vmware-svga,vgamem_mb=${VIDEO_RAM_MB:-64}"
)

# 显示模式:vnc = 无头运行(关闭查看器不会杀死虚拟机),gtk = 原生窗口
if [ "${DISPLAY_MODE:-gtk}" = "vnc" ]; then
  args+=(-display none -vnc "127.0.0.1:${VNC_DISPLAY:-1}")
  display_hint="VNC 127.0.0.1:$((5900 + ${VNC_DISPLAY:-1}))"
else
  args+=(-display gtk,grab-on-hover=on)
  display_hint="本地 GTK 窗口"
fi

# 调试:panic 时定格画面而不是重启循环(用于观察崩溃信息)
[ "${DEBUG_NO_REBOOT:-0}" = "1" ] && args+=(-no-reboot)

# 安装介质存在才挂载;装完系统删除 BaseSystem.img 后即自动跳过
if [ -f BaseSystem.img ]; then
  args+=(
    -device ide-hd,bus=sata.3,drive=InstallMedia
    -drive id=InstallMedia,if=none,file="BaseSystem.img",format=raw
  )
fi

echo ">>> 启动 $VM_NAME(RAM ${VM_RAM_MB}MB / ${VM_SMP} vCPU / VRAM ${VIDEO_RAM_MB:-64}MB),显示: $display_hint"
exec qemu-system-x86_64 "${args[@]}"
