# macOS on KVM

在 Intel Linux 主机上通过 QEMU/KVM 运行 macOS Sonoma。项目提供可复现的
上游版本锁定、统一配置、安装脚本和实机排错记录；不分发 macOS 镜像。

底层基于上游 [OSX-KVM](https://github.com/kholia/OSX-KVM)(版本锁定见 `vendor/LOCK`),
本仓库提供:统一配置、自动化脚本、文档。不 fork 上游,只做包装与定制。

## 使用条件

> [!WARNING]
> Apple 的 macOS 软件许可协议将 macOS 的安装和虚拟化限定在符合条款的
> **Apple 品牌硬件**上。使用前请阅读对应版本的
> [Apple 软件许可协议](https://www.apple.com/legal/sla/)。本项目不提供法律建议，
> 也不代表 Apple、OpenCore 或 OSX-KVM。

当前脚本的适用范围：

- **宿主系统**：Linux Mint、Ubuntu 或其他使用 APT 的 Debian 系发行版；
  首次安装依赖需要 `sudo`，之后启动虚拟机不需要 root。
- **处理器**：Intel x86_64，必须支持 VT-x、SSE4.1 和 AVX2；当前 CPU 参数针对
  13 代酷睿 Raptor Lake 调试。AMD、ARM 和 Apple Silicon 宿主未经验证。
- **虚拟化**：内核 KVM 可用，推荐 QEMU 8.2.2 或更高版本；
  `/sys/module/kvm/parameters/ignore_msrs` 必须为 `Y`。
- **内存**：宿主机至少 16GB，推荐 24GB 以上；默认给虚拟机分配 8GB。
- **存储**：建议至少预留 60GB 可用空间。系统盘虚拟容量为 256GB，采用 qcow2
  稀疏分配，但会随着 macOS 写入持续增长。
- **网络**：首次恢复镜像约 1GB，安装器还需从 Apple CDN 下载约 13GB；
  需要稳定网络，项目不提供第三方 macOS 镜像。
- **显示**：默认 `vmware-svga` 软件渲染，没有 Metal/GPU 加速。适合安装验证、
  命令行和轻量 GUI，不适合视频、3D、游戏或依赖 GPU 的生产工作。

本项目目前不承诺：

- iCloud、iMessage、Apple ID 或 DRM 功能可用；
- 睡眠、休眠、USB/PCI/GPU 直通和系统大版本升级稳定；
- 在未列出的硬件、发行版或 QEMU 版本上正常运行；
- 数据安全。重要数据必须在关机状态下另行备份。

## 已验证环境

- i5-13500H(VT-x ✓,AVX2 ✓)/ 31GB RAM / 411GB 空闲 / Iris Xe **单核显**
- QEMU 8.2.2 + libvirt 10 + virt-manager
- Linux Mint + KVM，macOS Sonoma 14.8.8 安装和启动成功
- Raptor Lake Iris Xe 没有可用的 macOS 图形加速驱动，因此保持软件渲染

## 虚拟机配置(conf/vm.env)

macOS **Sonoma 14** / 8GB RAM / 4 vCPU / 64MB 显存 / 256GB qcow2(稀疏)/ NAT + SSH 端口转发 2222

> vCPU 数量是排错结论:Raptor Lake 宿主上 6 vCPU 会触发 XNU 拓扑
> divide error panic,4 vCPU 稳定。详见 `docs/TROUBLESHOOTING.md`。

## 快速开始

```bash
git clone https://github.com/azel-ko/macos.git
cd macos

bash setup/00-deps.sh          # ① 依赖安装 + KVM 调优(需 sudo;装完【重新登录】)
bash setup/10-fetch-osx-kvm.sh # ② 克隆上游 OSX-KVM
bash setup/20-fetch-macos.sh   # ③ 下载 Sonoma 恢复镜像(苹果官方源,约1GB)
bash setup/30-create-disk.sh   # ④ 创建 256G 系统盘
bash setup/40-boot-macos.sh    # ⑤ 启动虚拟机,默认弹出本地 GTK 窗口
```

需要无头运行时:`DISPLAY_MODE=vnc bash setup/40-boot-macos.sh`,再用
`remote-viewer vnc://127.0.0.1:5901` 连接。

## 首次安装流程(虚拟机窗口内操作)

1. OpenCore 引导菜单选择 **macOS Base System (external)**(键盘方向键+回车)
2. 进入恢复环境 → **磁盘工具** → 选中 256GB 虚拟盘 → **抹掉**(APFS,命名 `Macintosh HD`)
3. 关闭磁盘工具 → **重新安装 macOS Sonoma**(在线下载约 13GB,全程 30~60 分钟)
4. 安装器会自动重启 2 次,OpenCore 默认项已指向安装器/系统,无需干预
5. 初始设置:语言/时区正常选;**Apple ID 建议跳过**(虚拟硬件上 iCloud 可能异常)

## 安装完成后

- macOS 内:系统设置 → 通用 → 共享 → 打开**远程登录**
  → 宿主机直接 `ssh -p 2222 <用户名>@localhost`
- 确认 `Macintosh HD` 能独立启动后，删除
  `vendor/OSX-KVM/BaseSystem.img` 可释放约 3GB，启动脚本会自动跳过安装介质。
- 关机状态下备份系统盘：
  `cp vendor/OSX-KVM/mac_hdd_ng.img vendor/OSX-KVM/mac_hdd_ng.img.bak`
- 后续日常启动只需：`bash setup/40-boot-macos.sh`

## 性能预期(诚实版)

| 场景 | 体验 |
|---|---|
| 命令行/编译/SSH | 接近原生 |
| 日常 GUI 应用(浏览器、办公软件) | 可用,动画有卡顿感 |
| 视频播放/3D/大型图形应用 | 较差；软件渲染模式不适合 |

## 路线图

- [x] P0 脚本化搭建 + 软件渲染 VM(当前)
- [ ] P1 安装后优化:SSH、共享文件夹(SMB)、分辨率、快照脚本
- [ ] P2 libvirt/virt-manager 托管(XML 模板,图形化管理)
- [ ] P3 受支持独立 GPU 的 PCI 直通研究(需要额外硬件)
- [ ] P4 评估远程应用集成；macOS 当前没有成熟的 RemoteApp 等价方案
