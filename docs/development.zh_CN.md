[English](development.md) · [返回首页](../README.zh_CN.md)

# 开发指南

## 架构与边界

```text
Passport.app (Swift / AppKit)
  ├─ launchd lifecycle requests
  └─ Unix socket owner + status subscription
       └─ Rust runtime
           ├─ Codex module: local/SSH collection, SQLite, rendering
           └─ device: USB/BLE, identity/capability negotiation
                └─ ESP32-C3 firmware
```

常驻部分为原生菜单栏应用、Rust 和每个远端的一条 SSH 子进程；不另起本机 App Server，不在远端安装自定义采集器。Python 用于固件工具、测试和旧实现，不是当前常驻服务。

远端使用现有 App Server 的只读轮询，不能假设新连接一定收到所有任务事件。本机桌面 App Server 没有当前实现可复用的控制 socket，因此保留文件／数据库兼容层。这些本地格式和远端 RPC 能力可能随 Codex 版本变化；升级后要重新验证。

## 代码入口

| 路径 | 职责 |
| --- | --- |
| `rust-bridge/src/runtime.rs`、`codex.rs`、`control.rs` | 生命周期、采集模块、本地控制 |
| `local.rs` | 本地任务生命周期与元数据 |
| `remote.rs`、`rpc.rs` | SSH、App Server RPC、远端采集 |
| `state.rs` | SQLite 检查点、去重、持久化投递 |
| `display.rs` | 额度、token、重置卡与显示数据转换 |
| `render.rs`、`text.c` | macOS CoreText 文字位图 |
| `device.rs`、`ble.rs`、`ble_macos.m` | USB／BLE 连接与认证；业务发送在 `codex_wire.rs` |
| `firmwares/codex/main/` | 固件页面、协议、刷新与提醒状态机 |
| `scripts/bridge-service.sh` | LaunchAgent 安装、启停、卸载 |
| `scripts/install-companion.py` | 绑定备份设备的应用区刷写工具 |
| `tests/` | 桥接兼容实现和集成行为测试 |

表中 Rust 文件均位于 `rust-bridge/src/`。`config/bridge.json` 保存远端别名与账号来源；`config/ble-device.json` 保存私密 BLE 配对信息；`reports/companion-state.sqlite3` 为运行状态。不要提交或分享配对密钥、原始备份和未脱敏日志。

## 环境与构建

当前主机为 Apple Silicon macOS；桥接依赖 Rust、系统框架 CoreText／CoreBluetooth 及 C／Objective-C 编译器。固件使用 ESP-IDF 5.5.3、ESP32-C3，工程工具链放在 `.toolchains/`。本工作区已有 `.venv`；重建工具环境时可使用：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cargo test --manifest-path rust-bridge/Cargo.toml
cargo clippy --manifest-path rust-bridge/Cargo.toml -- -D warnings
cargo build --release --manifest-path rust-bridge/Cargo.toml
```

更新 Rust 二进制后运行 `./scripts/bridge-service.sh restart`。首次从旧后台服务迁移时，先停止旧进程，再运行 `./scripts/bridge-service.sh install`。launchd 使用绝对路径，工作区移动后需重新安装；不在启动配置中复制 SSH agent socket 或密钥。

## 前台调试与诊断

先停止 launchd，避免设备锁冲突：

```bash
./scripts/bridge-service.sh stop
./rust-bridge/target/release/passport-bridge --workspace "$PWD" --log-file
# Ctrl+C 结束，然后恢复：
./scripts/bridge-service.sh start
```

Rust 支持 `--local-only`、`--remote ALIAS`、`--thread ID`、`--transport usb|ble|auto`。诊断需要单独的参数时以前台方式运行，不要修改生产服务的自动连接策略。`--dry-run` 默认使用临时状态，适合检查数据转换；具体参数以二进制 `--help` 和 `runtime.rs` 为准。

设备显示测试会临时替换任务页面，执行前关闭未读提醒并停止正式服务：

```bash
./scripts/bridge-service.sh stop
./rust-bridge/target/release/passport-bridge --workspace "$PWD" --device-check --transport usb
./scripts/bridge-service.sh start
```

换成 `--transport ble` 可做无线显示测试。不要把收到 ACK 当作实屏可读性、按键和声音的完整验收。

## 配对和账号接入

首次 BLE 配对需要 USB 和已安装的配套固件：

```bash
./scripts/bridge-service.sh stop
.venv/bin/python scripts/pair-ble.py
./scripts/bridge-service.sh start
```

配对密钥通过 USB 写入并保存于设备 NVS 与本地私密配置，断电后保留。正常重连不需要重复配对。

启用账号来源、切换登录账号或订阅后，运行 `.venv/bin/python scripts/verify-account-source.py devbox`（按配置替换别名）。此一次性核验会临时启动本地 App Server，退出时关闭；常驻桥接不会这样做。核验失败应查明身份差异，不要绕过检查。

## 协议与数据语义

`CDXP` 传输标题位图，`CDXL` 提交任务列表，`CDXM` 传输用量／日期／耗时／重置卡等元数据，状态包与对应 ACK 完成显示事务。重试必须使用不可变的同一事务与序号，不能把新标题和旧元数据混合发送。

设备 ACK 代表收到了数据，用户确认由设备的提醒栈负责。设备仅在 RAM 中保存最多八条 LIFO 提醒，任意设备重启或去重缓存淘汰后不保证严格 exactly-once。源离线保留最后快照并冻结耗时，不能误判任务成功完成。

额度为 `100 - usedPercent`；重置卡来自 `rateLimitResetCredits.availableCount`，与付费 credit balance 无关。七日 token 行按最新已报告日期倒序，缺失与零必须区分。当前轮次耗时包含工具执行和等待，不是整个会话总时长。

## 固件开发与安装

修改固件前先读 [AGENTS.md](../firmwares/codex/AGENTS.md)，按其路由阅读相关规范。遵守 LVGL 锁、非阻塞按键回调和应用退出清理要求。UI 变更仍需实屏验收。

在 Bash 中激活工具链并运行完整验证：

```bash
bash
source scripts/env.sh
.venv/bin/python scripts/firmware.py build codex
.venv/bin/python -m unittest discover -s tests -v
```

**这台实物保留原始分区表，没有模板的 Recovery 分区。** 不可擦除全片，不可把 merged 镜像从地址 0 直接刷入。原始 8 MB 备份包含设备身份，应私密保存。

```bash
./scripts/bridge-service.sh stop
.venv/bin/python scripts/install-companion.py            # 校验并预览
.venv/bin/python scripts/install-companion.py --install  # 写入应用区
./scripts/bridge-service.sh start
```

安装器从验证后的 `firmwares/codex/build/FoloToy-AI-Passport-full.bin` 提取应用，仅写 `0x10000`，上限 3 MB，并校验备份、设备序列号、bootloader／分区表与 `cardid`。不要绕过保护检查；脚本用于已备份的这台设备，并非通用刷机工具。恢复原应用需单独明确运行 `scripts/restore-original.py --restore`。

## 性能与验证标准

设备 ESP32-C3 为 160 MHz、400 KB SRAM、8 MB Flash，无 PSRAM，屏幕 240×320。控制内存的重点是 LVGL 对象、文字位图、传输缓冲和任务快照。

桥接保持增量读文件、有界队列、SQLite 小缓存；文字内容不变不重新栅格化或发送。设备仅可见值变化重绘，无持续动画。默认状态 3 秒、额度／重置卡 60 秒、token 300 秒；重置卡搭载额度请求，不新增轮询。

测量实际进程树，而非只测 Rust 主进程：

```bash
.venv/bin/python scripts/measure-resources.py --seconds 40 --output reports/resources.json
```

报告包括 Rust 与 SSH 的 RSS 和 CPU；RSS 相加可能重复计算共享页。设备 ACK 的 `heap`／`min_heap` 分别为当前与启动以来最低空闲堆，压力测试低点不能当作稳态占用。

交付区分编译、主机测试、设备协议测试和未验证项；不要把历史测量值或概念图当成当前性能与实屏证据。仅文档变更检查链接与命令准确性即可，无需刷写设备。

## 辅助信息页面

`rust-bridge/src/info.rs` 从现有额度响应提取重置卡，从 `State.sources` 生成来源健康状态；`companion_info.c` 负责有界 ASCII 帧解析与导航，`companion_info_ui.c` 通过一个 LVGL 绘制对象复用页面空间。固定中文标签使用 Noto Sans CJK 的 16 px 字形子集。

新增帧为 `CDXI|seq|available|quota_age|generation|known|count|timezone|source_count|name|healthy|...|title|status|granted|expires|description|type|...|END`，回复 `CDX_INFO_ACK seq`。字段中的管道与控制字符在主机端清理，不发送重置卡 ID、账号凭据或兑换指令。每卡限制名称 39、状态 15、日期 16、说明 159、类型 23 个 ASCII 字符，最多六卡／四来源；长文本显式省略。中文动态卡片文案暂不支持，固定界面中文可显示。

辅助载荷仅在内容变化或重新连接时发送，额度响应时间 generation 保证相同额度的成功刷新也能更新新鲜度；不新增轮询。USB/BLE 自测覆盖缺失详情、有效卡片与重复投递。桥接与固件需要配套升级。

完成页图片布局：168×60 标题加 170×16 工作区，合计仍为 3200 字节。`CDXM` 可选末字段传递最多 48 字符的 ASCII 主机名，每条提醒独立保存；主机名和耗时显示在下一行。修改图片布局时，固件和桥接服务必须一起更新。

## Passport 菜单栏应用

运行 `cargo build --release --manifest-path rust-bridge/Cargo.toml` 和 `./scripts/build-tray.sh`，再运行 `./scripts/bridge-service.sh install` 安装 LaunchAgent，最后打开 `macos-app/build/Passport.app`。需要 Swift 6／AppKit 和 macOS 13+。开发应用使用临时签名，应用包保存工作区路径；更新或移动前先退出应用。

`runtime.rs` 管理生命周期，`codex.rs` 拥有采集与持久提醒，`codex_wire.rs` 拥有 Codex 报文和图片缓存，`device.rs` 管理连接。`control.rs` 提供版本 1、换行分隔的 JSON 操作：`status`、`subscribe`、`reconnect`、`stop`。请求限制 4096 字节，最多八个连接，仅接受同一 UID；`reports/control` 权限 0700，socket 权限 0600。菜单持有 owner 订阅；托管启动允许 30 秒建立连接，失联后允许十秒恢复。前台诊断不需要菜单持有，但共享设备排他锁。

固件查询为 `PASSPORT?|END`，响应为 `PASSPORT|id|version|protocol|capability,capability|END`。协议 1 及 `codex-v1`、`completion-wide-v1`、`info-v1` 能力启用 Codex 发送模块，外观标识不决定代码选择。不支持或无握手时禁止发送业务数据，重连清除身份缓存；固件保留旧诊断工具的报文解析。

应用使用脚本内部的 `backend-start`、`backend-stop`、`backend-force-stop` 操作管理 launchd；用户使用公开操作。后台不设置 RunAtLoad／KeepAlive，公开命令通过 `app.sock` 进入同一菜单控制器。不要绕过应用执行 backend-start，否则托管所有权会超时退出。

验证包含 Rust 测试／clippy、`scripts/test-tray-control.py`、`scripts/test-tray-lifecycle.py`、固件完整检查、USB/BLE device-check 和 `scripts/test-usb-handover.py`。`scripts/measure-resources.py` 自动发现菜单栏／launchd PID 及子进程，分别报告 RSS、物理占用、CPU 和唤醒。

回滚：退出 Passport 并关闭其登录项，从 `backups/pre-tray` 恢复匹配的旧 Rust 和应用固件，再恢复 `bridge.plist` 及旧启动脚本。配对和数据原地保留。不要直接将合并镜像跨保护区域刷入；仍须使用保护区域校验的应用刷写流程。安装脚本生成带时间戳的私有备份，不要发布。

后续固件要复用自动连接，须保留 115200 波特率 USB 报文及现有加密 BLE 服务／认证约定，并保留 NVS 配对数据。能力协商不能让完全不同的蓝牙协议自动兼容。

[多固件工作区：新建、构建与安装](firmware-workspaces.zh_CN.md)
