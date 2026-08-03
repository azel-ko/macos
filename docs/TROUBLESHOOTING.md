# 排错指南

> 以下结论全部来自 2026-07 在 i5-13500H(Raptor Lake)+ QEMU 8.2.2 上的实测。

## 启动后立即卡死/重启循环(苹果 logo 不出现)

`kvm ignore_msrs` 未生效。检查:

```bash
cat /sys/module/kvm/parameters/ignore_msrs   # 必须输出 Y
```

输出 N 则重跑 `setup/00-deps.sh`,或 `echo Y | sudo tee /sys/module/kvm/parameters/ignore_msrs`。

## 进 XNU 内核瞬间崩溃(连 panic 信息都没有)

**CPU 型号仿真与宿主 CPU 冲突。** 实测 Raptor Lake(13代)上:

- `Haswell-noTSX`(上游默认)→ XNU 入口即 triple fault,必崩
- `-cpu host` → 与 6 核拓扑相同的 divide error panic
- `Penryn` → 无 AVX2,Sonoma 起不来
- ✅ **`Skylake-Client,-hle,-rtm`** → 稳定可用(启动脚本默认值)

## XNU 启动 0.68 秒 panic: `type 0=divide error`

`-serial file:macos-serial.log` 抓到:

```
panic(cpu 0 caller ...): Kernel trap at ..., type 0=divide error
```

**根因:vCPU 拓扑。** `-smp 6,cores=6,threads=1` 会让 XNU 在混合架构
(P核+E核)宿主上计算拓扑时除零。**改成 4 vCPU(cores=4,threads=1)即可**。
core 数排错期间固定为 4,不要盲目加核;想试 8 核请逐次验证。

## OpenCore 引导菜单键盘完全无响应

USB 键盘挂错了控制器。OVMF/OpenCore 的 UEFI 阶段**没有 XHCI 驱动**,
`-device usb-kbd,bus=xhci.0` 在引导菜单里是死的。

✅ 键鼠必须挂 EHCI(启动脚本已内置):

```bash
-device usb-ehci,id=ehci
-device usb-kbd,bus=ehci.0 -device usb-mouse,bus=ehci.0
```

xhci 控制器保留——进了 macOS 之后它照常工作。

## macOS 里鼠标不动/点击无效

**`usb-tablet` 是 HID 数字化仪(digitizer)**,macOS 把它当绘图板,
不驱动光标。必须用 **`usb-mouse`**(相对坐标)。

代价:相对坐标下 QEMU/VNC 里宿主与虚拟机光标不同步,
VNC 查看器里按 Ctrl+Alt 释放鼠标。这是正确行为,不要"修"它。

## macOS 里指针移动距离忽大忽小

macOS 指针加速对相对坐标鼠标生效:大步移动会 overshoot ~2x。
手工操作无感,自动化脚本(QEMU monitor `mouse_move`)必须用
小步(≤12px)慢走规避加速区间。参考实现见开发期脚本 `/tmp/vmdrive.py`
(闭环伺服:screendump 差分定位光标 + 比例步进)。

## 虚拟机内无网络

1. user-mode NAT 下 `ping` 不通是**正常**的(slirp 不支持 ICMP),用浏览器实测
2. 真不通则换网卡型号:编辑 `setup/40-boot-macos.sh`,启用注释里的
   `vmxnet3` 行(macOS 原生驱动),替换 `virtio-net-pci`

## 安装器下载极慢/失败

恢复环境内下载 13GB 走苹果 CDN。失败重试即可(进度保留)。
宿主机若走代理,注意 NAT 模式下虚拟机流量经宿主机转发,代理需在宿主机全局生效。

## QEMU 窗口不出现/后台启动即退出

`-display gtk` 在某些桌面/后台环境下静默失败。
需要后台常驻时用 VNC 无头模式:

```bash
DISPLAY_MODE=vnc bash setup/40-boot-macos.sh
remote-viewer vnc://127.0.0.1:5901
```

关闭查看器不会杀死虚拟机。日常本地操作默认使用延迟更低的 GTK 窗口。

## QEMU 窗口分辨率低/无法调整

启动脚本用 `OVMF_VARS-1920x1080.fd`(1080p)。
`vendor/OSX-KVM/` 内有其他分辨率变体可换。注意:**改 OVMF_VARS 会重置 NVRAM**。

## 磁盘占满

`mac_hdd_ng.img` 是稀疏文件,`du -h` 看实际占用。macOS 内删除文件不会自动收缩,
关机后执行 `qemu-img convert -O qcow2 mac_hdd_ng.img new.img` 重建收缩。

## "您的电脑遇到问题"反复重启(kernel panic)

1. 先按上面 divide error / CPU 型号两节排查
2. 收集 XNU 日志:OpenCore config.plist 的 boot-args 加
   `-v keepsyms=1 debug=0x144 serial=1 msgbuf=1048576`,
   QEMU 加 `-serial file:macos-serial.log`,panic 全文会落盘
3. `DEBUG_NO_REBOOT=1 bash setup/40-boot-macos.sh` 让 panic 定格不重启
