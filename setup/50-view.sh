#!/usr/bin/env bash
# 50-view.sh —— 用 remote-viewer 连接虚拟机的 VNC 显示(关闭窗口不影响虚拟机运行)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source conf/vm.env

PORT=$((5900 + ${VNC_DISPLAY:-1}))
if command -v remote-viewer >/dev/null; then
  exec remote-viewer "vnc://127.0.0.1:${PORT}"
elif [ -x /tmp/virtview-local/rootfs/usr/bin/remote-viewer ]; then
  # 免 root 本地版(setup/00-deps.sh 完整安装后可删)
  export LD_LIBRARY_PATH="/tmp/virtview-local/rootfs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  exec /tmp/virtview-local/rootfs/usr/bin/remote-viewer "vnc://127.0.0.1:${PORT}"
else
  echo "未安装 remote-viewer,可用任何 VNC 客户端连接 127.0.0.1:${PORT}"
  exit 1
fi
