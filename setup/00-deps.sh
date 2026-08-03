#!/usr/bin/env bash
# 00-deps.sh —— 安装依赖 + KVM 系统调优(需要 sudo,全脚本唯一需要 root 的步骤)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PKGS=(
  qemu-system qemu-utils ovmf            # QEMU/KVM + UEFI 固件
  virt-manager libvirt-daemon-system libvirt-clients
  uml-utilities git wget
  libguestfs-tools p7zip-full make
  dmg2img                                # 转换 BaseSystem.dmg
  genisoimage net-tools python3
)

echo ">>> 安装依赖包..."
sudo apt-get update
sudo apt-get install -y "${PKGS[@]}"

echo ">>> 配置 KVM ignore_msrs(macOS 必需,否则开机死循环)..."
echo 'options kvm ignore_msrs=Y' | sudo tee /etc/modprobe.d/kvm.conf
# 立即生效(免重启);若 kvm 模块参数不存在则忽略,重启后由 modprobe.d 兜底
if [ -w /sys/module/kvm/parameters/ignore_msrs ] || [ -e /sys/module/kvm/parameters/ignore_msrs ]; then
  echo Y | sudo tee /sys/module/kvm/parameters/ignore_msrs
fi

echo ">>> 启动 libvirtd 并配置用户组..."
sudo systemctl enable --now libvirtd
sudo usermod -aG kvm "$USER"
sudo usermod -aG libvirt "$USER"

echo
echo ">>> 校验(出现警告不影响基本使用):"
virt-host-validate || true

cat <<'EOF'

完成。注意两件事:
  1. 用户组变更需要【重新登录】桌面会话才生效(kvm 组)
  2. 若 virt-host-validate 报 IOMMU/安全启动警告,首阶段软件渲染可忽略,
     GPU 直通阶段再处理
EOF
