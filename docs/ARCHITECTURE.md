# 架构说明

## 组件关系

```
┌─────────────────────────── Linux Mint 宿主机 ───────────────────────────┐
│                                                                          │
│  setup/*.sh 自动化脚本 ──> vendor/OSX-KVM(上游,锁定commit)              │
│       │                        │                                         │
│       │                        ├─ OpenCore.qcow2   引导器( Hackintosh 启动 │
│       │                        ├─ OVMF_CODE/VARS   UEFI 固件             │
│       │                        ├─ BaseSystem.img   macOS 恢复镜像(可删)  │
│       │                        └─ mac_hdd_ng.img   系统盘(256G qcow2)    │
│       │                                                                  │
│       └─> qemu-system-x86_64 + KVM(i5-13500H VT-x)                     │
│                    │                                                     │
│         ┌──────────┴──────────┐                                         │
│         │  macOS Sonoma 虚拟机 │  显示: vmware-svga(64MB,软件渲染)       │
│         │  8GB RAM / 4 vCPU   │  网络: user-mode NAT, hostfwd 2222→22  │
│         └─────────────────────┘  声卡: ich9-intel-hda                   │
└──────────────────────────────────────────────────────────────────────────┘
```

## 关键决策记录

**为什么包装 OSX-KVM 而不是自研或 fork**
上游已解决最硬的问题:OpenCore 引导配置、SMC 模拟密钥、OVMF 固件、
macOS 各版本的 CPU 仿真参数。fork 会失去上游修复( macOS 更新经常破坏引导),
因此 `vendor/` 浅克隆 + LOCK 文件固定 commit,定制全部放在本仓库脚本层。

**CPU 仿真:为什么是 `Skylake-Client,-hle,-rtm` 而不是上游默认 Haswell-noTSX**
- Ventura+ 硬性要求 AVX2 → 上游默认的 Penryn 模型无 AVX2,排除
- 但实测(2026-07,Raptor Lake i5-13500H):**Haswell-noTSX 在进 XNU 瞬间
  triple fault**,加全社区补丁 flag 也一样;`-cpu host` 则触发拓扑 divide panic
- Skylake-Client 自带 AVX2、被 Sonoma 原生支持,实测稳定 → 采用
- `-hle,-rtm`:13500H 的 TSX 已被微码禁用,QEMU 模型默认带这两个 flag 会
  导致行为不一致,显式去掉

**vCPU 为什么是 4 而不是更多**
`-smp 6,cores=6,threads=1` 时 XNU 启动 0.68s 即 `divide error` panic
(serial 日志实证)——混合架构宿主上报的拓扑让 XNU 算出 0 做除数。
4 vCPU(cores=4,threads=1)绕开。想加核需逐个验证,别一次跳太多。

**输入设备:EHCI + usb-mouse 的两个坑**
- OpenCore/OVMF 引导阶段**没有 XHCI 驱动**:usb-kbd 挂 xhci 则引导菜单
  键盘全死。键鼠挂 EHCI 后引导菜单和 macOS 内都正常
- `usb-tablet` 在 HID 描述符里是**数字化仪**,macOS 当绘图板处理、不驱动
  光标;必须用 `usb-mouse`(相对坐标)。相对坐标 + macOS 指针加速会让
  自动化脚本 overshoot,小步慢走(≤12px/步)规避

**显示模式选择**
本地使用默认 `-display gtk`,减少 VNC 编解码和传输带来的交互延迟。
需要后台常驻或脚本化截图时可用 `DISPLAY_MODE=vnc` 临时切换到
VNC 无头模式(127.0.0.1:5901);关闭查看器不会杀死虚拟机。

**为什么先软件渲染**
开发机只有 Raptor Lake Iris Xe 单核显，macOS 没有适用的图形驱动；即使直通也
无法提供正常的 Metal 加速，而且单 GPU 直通会导致宿主机失去显示。
`vmware-svga` 设备有 macOS 原生驱动，是无直通下的可用显示方案，但没有
Metal 加速 → 窗口合成走 CPU，动画会卡顿。

**网络选型**
user-mode NAT(slirp)零配置、无需 root,hostfwd 提供 SSH 通道。
代价:虚拟机不可被局域网直达、无 ICMP(ping 不通属正常)。
后期需要局域网服务(AirDrop 替代、文件共享)时切桥接/tap。

**macOS 与应用数据获取渠道**
恢复镜像由苹果官方 CDN 下载(fetch-macOS-v2.py 走苹果 sucatalog 目录),
不经过第三方镜像站,无篡改面。安装器 13GB 由恢复环境内在线下载,同样来自苹果。

## 文件共享方案(P1 实现)

macOS 不支持 virtio-fs/9p,候选:
- **SMB**(宿主机 Samba 共享目录,macOS 访达原生挂载)— 首选
- sshfs-macFUSE(macOS 侧装 macFUSE,维护状态一般)— 备选
- SSH/rsync 单向同步 — 保底

## 后续阶段

- P2: 生成 libvirt XML 导入 virt-manager(快照、自动启动、图形化控制台)
- P3: 如增加受 macOS 支持的独立 GPU，再评估 VFIO PCI 直通
- P4: 评估远程应用集成；macOS 当前没有成熟的 RemoteApp 等价方案
