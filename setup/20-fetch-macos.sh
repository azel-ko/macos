#!/usr/bin/env bash
# 20-fetch-macos.sh —— 从苹果官方服务器下载 macOS 恢复镜像并转换为 QEMU 可用格式
# 产物: vendor/OSX-KVM/BaseSystem.dmg -> BaseSystem.img
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source conf/vm.env

DIR="vendor/OSX-KVM"
[ -d "$DIR" ] || { echo "先运行 setup/10-fetch-osx-kvm.sh"; exit 1; }
cd "$DIR"

if [ -f BaseSystem.img ]; then
  echo ">>> BaseSystem.img 已存在,跳过(删除后重跑可重新下载)"
  exit 0
fi

if [ ! -f BaseSystem.dmg ]; then
  echo ">>> 解析下载菜单中的 [$MACOS_MENU_NAME] ..."
  # 空输入让脚本打印完菜单后自行退出,借此解析版本编号
  MENU="$(python3 fetch-macOS-v2.py </dev/null 2>/dev/null || true)"
  CHOICE="$(printf '%s\n' "$MENU" \
    | grep -iE "^[[:space:]]*[0-9]+[.)].*$MACOS_MENU_NAME" \
    | grep -oE '[0-9]+' | head -1)"
  if [ -z "${CHOICE:-}" ]; then
    echo "!! 菜单中未找到 $MACOS_MENU_NAME,实际菜单如下:"
    printf '%s\n' "$MENU"
    exit 1
  fi
  echo ">>> 选择第 $CHOICE 项,开始下载(约 1GB,视网速需几分钟到几十分钟)..."
  # 非 TTY 环境(后台/cron)下 fetch 脚本的校验步骤会因 ioctl 误报失败,
  # 用 script(1) 提供伪终端规避;交互终端则直接运行
  if [ -t 0 ]; then
    printf '%s\n' "$CHOICE" | python3 fetch-macOS-v2.py
  else
    printf '%s\n' "$CHOICE" | script -qec "python3 fetch-macOS-v2.py" /dev/null
  fi
fi

command -v dmg2img >/dev/null || { echo "!! 缺少 dmg2img,请先运行 setup/00-deps.sh(dmg 已下载,重跑本脚本即可续上)"; exit 1; }

echo ">>> 转换 dmg -> img ..."
dmg2img -i BaseSystem.dmg BaseSystem.img
echo ">>> 完成: $(du -h BaseSystem.img | cut -f1) BaseSystem.img"
