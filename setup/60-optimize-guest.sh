#!/bin/bash
# 在 macOS 登录用户的终端运行;不需要 sudo,先备份再减少桌面合成负担。
set -euo pipefail

if [ "$(uname -s)" != Darwin ]; then
  echo "请在 macOS 虚拟机内运行本脚本,或通过 SSH 传入 bash。"
  exit 1
fi

domains=(NSGlobalDomain com.apple.universalaccess com.apple.finder com.apple.dock)
accessibility_pending=0
if [ "${1:-}" = "--restore" ]; then
  backup="${2:?用法: $0 --restore 备份目录}"
  for domain in "${domains[@]}"; do
    if [ ! -f "$backup/$domain.plist" ] && [ ! -f "$backup/$domain.absent" ]; then
      echo "缺少备份: $domain"
      exit 1
    fi
  done
  for domain in "${domains[@]}"; do
    if [ -f "$backup/$domain.plist" ]; then
      if ! defaults import "$domain" "$backup/$domain.plist"; then
        if [ "$domain" = com.apple.universalaccess ]; then
          accessibility_pending=2
          echo "辅助功能偏好受保护;请按备份中的值在系统设置 > 辅助功能 > 显示中恢复。"
        else
          exit 1
        fi
      fi
    elif [ -f "$backup/$domain.absent" ]; then
      defaults delete "$domain" 2>/dev/null || true
    fi
  done
else
  root="$HOME/Library/Application Support/macos-kvm-tuning"
  umask 077
  mkdir -p "$root"
  backup="$(mktemp -d "$root/backup-XXXXXXXX")"
  for domain in "${domains[@]}"; do
    if defaults read "$domain" >/dev/null 2>&1; then
      defaults export "$domain" "$backup/$domain.plist"
    else
      touch "$backup/$domain.absent"
    fi
  done
  echo "原始偏好设置已备份到: $backup"
  defaults write NSGlobalDomain NSAutomaticWindowAnimationsEnabled -bool false
  defaults write com.apple.finder DisableAllAnimations -bool true
  defaults write com.apple.dock launchanim -bool false
  defaults write com.apple.dock expose-animation-duration -float 0.1
  defaults write com.apple.dock mineffect -string scale
  for key in reduceMotion reduceTransparency; do
    if [ "$(defaults read com.apple.universalaccess "$key" 2>/dev/null || true)" != "1" ]; then
      if ! defaults write com.apple.universalaccess "$key" -bool true; then
        accessibility_pending=2
        echo "无法修改辅助功能设置 $key;请在系统设置 > 辅助功能 > 显示中开启。"
      fi
    fi
  done
fi

killall Dock 2>/dev/null || true
killall Finder 2>/dev/null || true
echo "已更新桌面偏好设置;辅助功能设置可能需要注销后完全生效。"
echo "这减少软件渲染负担,不会启用 Metal。"
exit "$accessibility_pending"
