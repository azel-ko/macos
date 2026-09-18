#!/usr/bin/env bash
# 10-fetch-osx-kvm.sh —— 克隆上游 OSX-KVM 到 vendor/,用 vendor/LOCK 固定版本保证可复现
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

REPO="https://github.com/kholia/OSX-KVM"
DIR="vendor/OSX-KVM"
LOCK="vendor/LOCK"
PATCH="$PWD/patches/opencore-local.patch"

if [ -d "$DIR/.git" ]; then
  echo ">>> 已存在: $DIR(commit $(git -C "$DIR" rev-parse --short HEAD))"
else
  mkdir -p vendor
  if [ -f "$LOCK" ]; then
    # 有锁定记录:完整克隆后 checkout 到锁定的 commit
    git clone "$REPO" "$DIR"
    git -C "$DIR" checkout "$(cat "$LOCK")"
  else
    git clone --depth 1 "$REPO" "$DIR"
  fi
fi

if git -C "$DIR" apply --reverse --check "$PATCH" 2>/dev/null; then
  echo ">>> OpenCore 本地补丁已应用,跳过"
elif git -C "$DIR" apply --check "$PATCH"; then
  git -C "$DIR" apply "$PATCH"
  echo ">>> 已应用 OpenCore 本地补丁"
else
  echo "!! OpenCore 与补丁不兼容,请检查上游版本和本地修改;现有文件未覆盖"
  exit 1
fi

git -C "$DIR" rev-parse HEAD > "$LOCK"
echo ">>> 版本已锁定: $(cat "$LOCK") -> $LOCK"
