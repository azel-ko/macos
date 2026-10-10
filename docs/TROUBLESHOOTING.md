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

本机引导阶段使用 EHCI 键盘(启动脚本已内置):

```bash
-device usb-ehci,id=ehci
-device usb-kbd,bus=ehci.0
```

xhci 控制器及其 tablet 保留给 macOS 使用。

## macOS 里鼠标不动/点击无效

默认将 `usb-tablet` 接到 `xhci.0`，为 macOS 提供绝对定位，
同时保留 EHCI 键盘供固件使用。
默认不同时启用相对 USB 鼠标，避免后激活的设备让 GTK 仍选择相对模式。
完整关机后按最终配置再次启动，`query-mice` 已自动显示 Tablet 为
`current: true, absolute: true`，无需手动执行 `mouse_set`。
2026-10-10 本机 Sonoma 14.8.8 实测绝对定位正常；
连续五次 QMP 坐标输入与来宾 AppKit 读回坐标吻合，误差小于 0.03 像素。
此前“tablet 是数字化仪，不能驱动光标”的说明不准确；
QEMU 8.2.2 的 [tablet HID 描述符](https://github.com/qemu/qemu/blob/v8.2.2/hw/usb/dev-hid.c)
实际使用 Generic Desktop / Mouse。

完整启动后的 Safari 本地交互复测连续 20 次点击全部送达，
输入 `kvm-check-123` 和滚轮滚动通过。
QMP 鼠标按下至浏览器处理点击并经 HTTP 回传的中位间隔 35.15ms、
P95 36.43ms、最大 37.64ms；其中包含测试刻意按住鼠标的 30ms，
以及 HID、浏览器和回传路径，不包含显示呈现延迟。
这不是端到端显示延迟或整机日用性能保证。

其他系统若绝对定位不可用，可用 `VM_POINTER=mouse` 启动以回退。
相对定位需要抓取鼠标，Ctrl+Alt+G 切换 GTK 抓取；VNC 查看器快捷键以其菜单为准。

## macOS 里指针移动距离忽大忽小

默认 XHCI tablet 使用绝对定位，不需要补偿相对鼠标加速。
回退到 `VM_POINTER=mouse` 时，macOS 指针加速仍会影响移动距离；
自动化应读回来宾光标位置后修正，不应将相对位移当成屏幕坐标。

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

启动脚本默认使用 4MB CODE 和独立的 `OVMF_VARS_4M.macvm.fd`。
首次启动从系统的 `OVMF_VARS_4M.fd` 模板复制，之后保留来宾写入的变量。
原来的 `OVMF_VARS-1920x1080.fd` 只有 128KB，与 4MB CODE 不匹配，
本机此前无法保存默认启动项。脚本现在拒绝混用固件尺寸。
更换后已实测 NVRAM 测试变量跨重启保留，且无需键盘干预即可自动启动系统盘；
临时测试变量已删除。
不要用旧版 VARS 调分辨率；切换 VARS 相当于切换 NVRAM，会重置启动偏好。
显卡没有来宾驱动时，分辨率也受固件 framebuffer 限制。

## 桌面非常卡顿

2026-10-10 本机确认：宿主机 Mesa 正在使用 Iris Xe 硬件加速，
但未限制亲和性时 QEMU 主线程及多个 vCPU 会被调度到 E 核。
启动脚本现按宿主 CPU 最大频率和物理核拓扑选择最快的一组 CPU；
若这组 CPU 不足以承载配置的物理核数，则保留当前允许的全部 CPU。
本机自动选择的范围为 `0-7`，不修改宿主机 SMT 或其他应用的亲和性。

日常启动保留已实测稳定的 4 vCPU / 8GB，使用本地 GTK 窗口：

```bash
ATTACH_INSTALL_MEDIA=0 bash setup/40-boot-macos.sh
```

OpenCore 若选中了 EFI，选择 `Macintosh HD` 后按 **Ctrl+Enter** 设置默认启动项。
GTK 默认 `gl=on`，只影响宿主机窗口呈现，不代表来宾获得 Metal。
其他主机若不支持它，可用 `DISPLAY_GL=off` 启动。
`VM_CPU_AFFINITY=off` 可取消 CPU 限制，用于对比排错。

磁盘默认使用 `cache=none,aio=threads,discard=unmap`，减少宿主机磁盘页缓存
重复占用，系统盘声明 `rotation_rate=1,discard_granularity=512`。
本机重启后已确认来宾显示 Solid State / TRIM Support: Yes，保留正常 flush 语义。
宿主机提示内存不足时，
先保存并关闭不需要的重型应用，不要继续给虚拟机增加内存。

将 `setup/60-optimize-guest.sh` 复制到 macOS，以登录用户运行：

```bash
bash 60-optimize-guest.sh
```

开启远程登录后也可从宿主机执行（用户名按实际账户修改）：

```bash
ssh -p 2222 azel@127.0.0.1 'bash -s' < setup/60-optimize-guest.sh
```

脚本先备份原始偏好，再减少透明效果、窗口和 Dock 动画，不关闭锁屏或系统服务。
辅助功能设置可能需要注销后完全生效。备份保存在
`~/Library/Application Support/macos-kvm-tuning/`，
使用 `bash 60-optimize-guest.sh --restore "备份目录"` 恢复；
恢复会将涉及的四个偏好域还原到备份时状态。
若恢复时辅助功能域同样受保护，脚本会恢复其他三个域并返回状态码 2，
辅助功能选项需要在系统设置中按备份值恢复。
Sonoma 可能阻止 SSH 修改辅助功能偏好；脚本仍会应用 Finder/Dock 动画设置，
并以状态码 2 提示到“系统设置 > 辅助功能 > 显示”开启“减弱动态效果”和
“减少透明度”。不需要为此关闭 SIP 或授予完整磁盘访问权限。

本机另外通过系统设置开启减弱动态效果、关闭自动播放动态图，
并切换到系统自带的黑色静态壁纸。旧屏保使用“全部随机”轮换 134 段航拍，
动态素材目录约 37GB，登录后曾观察到 `idleassetsd` 持续下载和占用 CPU。
原始桌面偏好保存在来宾的
`~/Library/Application Support/macos-kvm-tuning/backup-facVEwPn/`；
壁纸 Index.plist 和电源参数另存于同级 `backup-WS0WAfEK/`。
原始来宾电源设置是闲置 1 分钟睡眠，本次改为 `sudo pmset -a sleep 0`，
保留显示器 10 分钟熄屏和原锁屏配置；恢复自动睡眠可用 `sudo pmset -a sleep 1`。

登录恢复列表曾包含 17 个应用，登录后会依次恢复 IDEA、地图、播客等程序。
本次在正常关机对话框取消“再次登录时重新打开窗口”，
确认 `com.apple.loginwindow` 中 `TALLogoutSavesState` 为 `0`，
并在下一次登录后验证前台应用列表只有 Finder。
原始普通域和 currentHost 域备份在来宾
`~/Library/Application Support/macos-kvm-tuning/session-before-20261010/`。
以后正常关机时保留该选项未勾选；需要恢复窗口时可重新勾选。
首次账户设置窗口可能阻止关机，先取消该应用的设置并正常退出后重试。

`system_profiler SPDisplaysDataType` 实测仍显示 VRAM 3MB / No Kext Loaded。
QEMU 的 64MB VRAM 配置不代表 macOS 已加载 SVGA 加速驱动，
GTK OpenGL 也不会为来宾提供 Metal。

2026-10-10 调优后，临时本地网页的 500 行列表自动滚动测试持续约 10 秒：
Safari 平均帧回调率 30Hz，中位间隔 33ms，P95 34ms，最大 46ms，
没有超过 50ms 的间隔。这衡量 JavaScript `requestAnimationFrame` 回调节奏，
不是端到端显示帧率，也没有与原配置做严格 A/B 对比。
暖机后的单次空闲采样约 96% CPU idle；复杂网页、IDE 和视频仍需按实际负载验收。

本次调优前已在关机状态创建系统盘内部快照
`before-daily-tuning-20261010`，并备份原有 OVMF VARS。
关闭虚拟机后可用 `qemu-img snapshot -l vendor/OSX-KVM/mac_hdd_ng.img` 查看。
恢复系统盘快照会丢弃之后的来宾改动，包括本次密码重置、SSH 配置和桌面调优；
不应在虚拟机运行时操作。

启动脚本会在创建控制 socket 前检查启动锁及镜像锁；提示“已经在运行”时
使用现有虚拟机。QMP 位于 `/tmp/macvm-qmp.sock`，用于检查实际 vCPU、
KVM 状态和块设备配置。软件渲染的交互体验仍需实机验收，不能保证 60 FPS。

## 磁盘占满

`mac_hdd_ng.img` 是稀疏文件,`du -h` 看实际占用。macOS 内删除文件不会自动收缩,
关机后执行 `qemu-img convert -O qcow2 mac_hdd_ng.img new.img` 重建收缩。

## "您的电脑遇到问题"反复重启(kernel panic)

1. 先按上面 divide error / CPU 型号两节排查
2. 收集 XNU 日志:OpenCore config.plist 的 boot-args 加
   `-v keepsyms=1 debug=0x144 serial=1 msgbuf=1048576`,
   QEMU 加 `-serial file:macos-serial.log`,panic 全文会落盘
3. `DEBUG_NO_REBOOT=1 bash setup/40-boot-macos.sh` 让 panic 定格不重启
