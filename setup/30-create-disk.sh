#!/usr/bin/env bash
# 30-create-disk.sh —— 创建 macOS 系统盘(qcow2 稀疏文件,初始几乎不占空间)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source conf/vm.env

DIR="vendor/OSX-KVM"
[ -d "$DIR" ] || { echo "先运行 setup/10-fetch-osx-kvm.sh"; exit 1; }

if [ -f "$DIR/$VM_DISK_FILE" ]; then
  echo ">>> $VM_DISK_FILE 已存在:"
  qemu-img info "$DIR/$VM_DISK_FILE" | grep -E 'virtual size|disk size'
  echo "(如需重建,手动删除后重跑 —— 注意:盘内数据会全部丢失)"
  exit 0
fi

qemu-img create -f qcow2 "$DIR/$VM_DISK_FILE" "$VM_DISK_SIZE"
echo ">>> 已创建 $VM_DISK_FILE(虚拟容量 $VM_DISK_SIZE,稀疏分配)"
