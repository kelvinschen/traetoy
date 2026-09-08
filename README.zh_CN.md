[English](README.md)

# Passport 工作区

[使用指南](docs/usage.zh_CN.md) · [开发指南](docs/development.zh_CN.md)

共用 macOS 菜单栏与 Rust bridge，支持多个独立固件工作区。现有 Codex 仪表盘位于 `firmwares/codex`。用 `.venv/bin/python scripts/firmware.py new my-clock` 新建独立应用，详见[多固件工作区](docs/firmware-workspaces.zh_CN.md)。

以下章节介绍内置 Codex 固件。

通过 Mac 的 BLE／USB 连接，把 Codex 账号额度与本地／SSH 任务完成状态显示到 ESP32-C3 设备。不需要 Wi-Fi 或 API Key。使用时 Mac 需要保持唤醒、运行桥接程序并连接设备。

设备仅在显示值变化时重绘，数据包序号和同一分钟内的秒数变化不会触发重绘。按键和数据到达直接唤醒应用循环。一分钟无按键或新提醒后，背光占空比从 75% 降至 35%；按键按下或新提醒立即恢复 75%。屏幕保持可见，监控继续运行。电量每 30 秒采样，BLE 分片在协商 MTU 允许时使用最多 244 字节。

[性能与省电验证记录](reports/device-performance-result.zh_CN.md)。

连续一小时无新提醒时自动关闭背光，监控继续运行。手动唤醒重新计时一小时；普通数据更新和亮屏时的导航不延长计时。任意功能键仅唤醒、不导航；新完成提醒自动亮屏并播放提示音。息屏期间暂停提醒可见计时和画面重绘。左侧独立电源键控制硬件电源，未作为软件按键暴露。

## BLE 连接（Rust v0.4）

Rust 桥接已支持 BLE 与 USB。默认 `auto` 优先使用可用的 USB 数据连接，USB 不可用时连接已配对的 BLE 设备；任务和账号采集逻辑不变。Mac 和设备需要保持开机、唤醒。BLE 无需 Wi-Fi 或公司网络认证。

首次设置时保持 USB 连接：

```bash
.venv/bin/python scripts/bridge-service.py stop
.venv/bin/python scripts/pair-ble.py
.venv/bin/python scripts/bridge-service.py start
```

解锁 Mac 并允许首次蓝牙权限请求。若曾拒绝，在“系统设置 → 隐私与安全性 → 蓝牙”中允许 macOS 显示的对应应用，然后重启服务。不需要在 macOS 蓝牙设置里手工配对：应用密钥通过 USB 写入。密钥保存在权限为 0600 的 `config/ble-device.json` 和设备 NVS 中，请勿分享该文件。重复执行配对会沿用已有密钥。

自动模式同一时刻只保持一种传输连接。可用 USB 优先，打开串口前先关闭已有 BLE；USB 正常时不连接、扫描或保活蓝牙。没有可用 USB 才连接已配对的 BLE，并每三秒检查 USB 是否出现。顶部只显示当前接口的 USB 或蓝牙图标，颜色为橙色。打开串口保留 DTR／RTS 状态，避免误触发设备复位。切换时清空位图缓存并重试同一待发事务。BLE 失败后有五秒重试冷却，USB 通信失败后该端点退避十五秒。配对断电保留，未读提醒仍在设备内存中。

使用 `start --transport usb` 强制 USB，或 `start --transport ble` 仅使用 BLE。切换前先停止服务。Python 备用引擎仍仅支持 USB。没有新增独立 App Server 或远端 BLE 辅助服务。

停止服务并清空未读提醒后，运行 `rust-bridge/target/release/passport-bridge --device-check --transport usb` 可验证 0/1/2/16 个任务及完整替换；换成 `--transport ble` 可执行同样的无线测试。`--ble-check` 验证认证往返、重放／篡改拒绝和重连，不创建任务提醒。诊断与服务共用设备排他锁，显示测试会临时替换任务画面，结束后请恢复正式监控。

协议、资源测量和待验收项目见 [BLE 设计与验证报告](reports/ble-implementation-result.zh_CN.md)。

## 启动

使用原生菜单栏应用 Passport 管理。打开应用即启动服务；停止服务保留菜单栏，退出应用则停止后台。登录启动是独立设置。使用及安装说明见 [使用文档](docs/usage.zh_CN.md) 和 [开发文档](docs/development.zh_CN.md)。

```bash
open macos-app/build/Passport.app
./scripts/bridge-service.sh status
./scripts/bridge-service.sh stop
./scripts/bridge-service.sh start
./scripts/bridge-service.sh quit
```

编译：`cargo build --release --manifest-path rust-bridge/Cargo.toml`。更新二进制后重启服务。Python 仍用于测试和固件工具。手动前台调试前先停止后台服务：

```bash
./scripts/start-companion.sh
# 仅展示配置主机中的一个任务：
./scripts/start-companion.sh --thread 你的任务UUID
# 旁路检查实时数据，不操作设备或正式通知数据库：
./scripts/start-companion.sh --dry-run --once
# Ctrl-C 停止。
```

运行 `.venv/bin/python scripts/restore-original.py` 只检查备份；需要恢复原身份卡应用时再加 `--restore`，并先停止桥接程序。

PAPER METER 界面使用官方 Codex 图标，不显示声音开关和底部操作提示。主页短按确定键优先打开未确认提醒，清空后才进入运行任务标题列表，上下键切换任务／翻页，长按确定键返回主页。提醒页短按确定键确认最新一条并显示下一条，全部确认后返回此前页面。长按确定键暂时返回主页，不确认或清空提醒。新完成任务立即置顶；顶部勾号旁显示未确认数量，所有页面均可见。设备在内存中保留最近八条压缩快照，满容量时淘汰最旧一条；设备重启后清空。每条提醒累计展示 30 秒后自动确认；新提醒打断或返回主页会暂停计时，恢复时继续剩余时间，全部结束后返回原页面。近期重复传输不会重复入栈或响铃。完成页左侧为小勾，右侧展示最多三行标题、耗时和工作区；标题／工作区图像和耗时在完成时固定，不会被后台同步覆盖。完成提示音保持开启，音频芯片音量为 100%。顶部只显示当前使用的 USB 或蓝牙图标，颜色为橙色。电池图标为 32 × 16 像素，内部用 13 px 字体显示电量数字，省略百分号，填充区域内文字反色，不再单独占用一行连接文字。默认关注本机所有主任务，以及 `config/bridge.json` 指定的 SSH 主机（当前为 `devbox`），每轮回复完成后提示一次；中断显示 “Task stopped”，不会增加完成数量。不监控云端任务。第一次接入建立基线，不提醒历史完成；之后重启或重连会从已保存检查点补查执行轮次，包括期间已归档的任务。设备接收与用户已读不同，八条内存 LIFO 仍由设备管理。

额度复用 `config/bridge.json` 中 `account_host` 指定的现有远程 App Server，与远程任务共用同一条 SSH 连接，每 60 秒调用 `account/rateLimits/read`。剩余百分比为 `100 - usedPercent`，窗口按实际时长标注；缺失窗口直接隐藏，超过 180 秒未更新显示过期，设备心跳中断 20 秒显示断连。设备只接收百分比、重置时间、数量和任务标题位图。账号凭证和对话不会传到设备。中文标题通过 macOS CoreText 和 Arial Unicode 字体绘制，采用 20 像素字号和四级灰度透明度抗锯齿。列表最多显示 16 个运行任务，每页两个；每项显示项目名、最多两行标题和简短耗时。项目名从任务工作目录识别；Git 工作树和仓库子目录映射至原仓库名，普通目录使用目录名。项目识别有缓存；显示内容不变时跳过渲染和位图传输。

远程任务通过持久 SSH 连接使用现有 `codex app-server proxy`，其上运行 WebSocket JSON-RPC，不在远端安装自建采集器。使用 `thread/list`、`thread/read`、分页 `thread/turns/list` 获取标题、目录、状态和耗时；`itemsView=notLoaded` 避免获取对话条目。远程项目优先用 `project/list` 返回的名字，否则用目录名，并附带 SSH 主机别名；不会在 Mac 上对远程路径执行 Git。任务发现约十秒一次，已知运行任务约三秒检查一次。本版使用只读轮询，不假设新增连接会收到所有执行完成事件。初始化通过 `optOutNotificationMethods` 关闭本监控连接不需要的通知推流，不影响桌面连接。

这台 Mac 的桌面 App Server 使用 stdio，没有可附加的控制 socket，所以本地任务保留生命周期日志兼容读取（`task_started`、`task_complete`、`turn_aborted`），验证版本为 CLI 0.153.2。Rust 直接以只读方式查询本地 `state_*.sqlite` 中的标题／工作目录元数据；不再额外启动本机 App Server。生命周期文件和数据库都是版本相关的兼容接口。未变化的文件跳过，旧的不活跃文件从跟踪集合退休，提醒去重持久化到 SQLite。若本地任务崩溃且缺少结束事件，状态可能无法收敛，不会因此误报完成。

数据源在独立工作线程中查询，网络查询不会阻塞设备刷新。来源断线时保留最后任务快照，冻结耗时，项目标签附带 `?`。SQLite 保存来源检查点、待投递提醒和“主机／任务／执行轮次”去重键；已投递记录保留三十天，待投递提醒不丢弃。跨进程重启的提醒重试复用已保存序号；一次设备重试中的标题、元数据和状态保持一致。设备 ACK 仅表示收到，不表示用户已读；任意设备重启或固件去重缓存淘汰后，不保证严格只投递一次。

Token 用量每五分钟通过官方 `account/usage/read` 接口读取。设备显示最近已上报日期的单日用量，以及截至该日的七个自然日范围内已返回日桶的合计，单位为 K／M／B tokens。日期使用服务端桶日期，不假设其为本地时区。缺失或请求过期显示 `--`，不会把缺失的今天数据显示成零。这是 token 活动统计，不是订阅剩余额度或账单；其七天统计范围和额度重置窗口独立。接口可能延迟上报，界面上的日期用于明确这一点。

任务计时针对当前一轮回复，包括工具执行和等待时间。运行时长使用记录中的开始时间；完成耗时优先使用原生 `durationMs`（本地日志兼容字段为 `duration_ms`），缺失时用起止时间差，未知时隐藏；耗时显示为 `<1m`、`3m` 或 `1h 12m`，没有前缀和秒数。不是任务所有历史轮次的累计耗时。

桥接程序在打开文件前跳过未变化的会话文件，并先筛选生命周期记录再解析 JSON。启动基线之后只读取追加字节；缓存显示内容签名，仅标题变化时重新绘制并传输。设备状态／耗时约每三秒刷新，额度每分钟刷新，账号 token 每五分钟刷新。Mac 常驻进程为原生菜单栏应用、Rust 主进程及每个已配置远端一条 SSH；没有 Python、Node 或独立本机 App Server 常驻。Rust 使用有界消息队列、增量文件读取、受限 SQLite 缓存，以及少量调用 CoreText 的 C 代码。监控任务不调用模型。可运行 `.venv/bin/python scripts/measure-resources.py --seconds 40 --output reports/resources.json` 测量完整桥接进程树；分别报告 RSS 和物理占用；RSS 合计可能重复计算共享页面。

账号来源在启用前必须确认与本机相同：`.venv/bin/python scripts/verify-account-source.py devbox`。该一次性工具会启动临时本机 App Server 比较账户，退出时关闭，只保存私有 SHA-256 指纹。Rust 定期校验远端指纹，账户不一致时停止更新账户数据，但继续采集任务。更换本机登录账户／订阅类型后需重新核验。远端断线或关闭 SSH 时，额度和 Token 先保留缓存，随后分别标记过期／显示 `--`；不会悄悄启动本机替代服务。当前指纹已完成核验。

接入 BLE 之前的迁移测量：Rust + SSH 共 31.73 MiB RSS；断线重连样本峰值 32.92 MiB。详见 [迁移与测量报告](reports/rust-migration-result.zh_CN.md)，含测量口径和未验证项。

## 工作区内容

- `firmwares/codex/`：官方参考项目，开发分支为 `feature/codex-companion`。
- `rust-bridge/`：当前常驻服务，Rust + 系统 SQLite + CoreText 小型 C 接口。
- `scripts/companion.py`、`scripts/passport/`：Python 对照／回退实现。
- `config/bridge.json`：SSH 主机别名；`--remote 别名` 覆盖配置，`--local-only` 关闭 SSH。
- `reports/companion-state.sqlite3`：私有持久化状态；旁路模式默认用临时数据库。
- `scripts/device.py`：发现设备、读取芯片信息和串口日志。
- `tests/`：桥接程序行为测试。
- `backups/`：原设备完整 8 MB Flash 和 SHA-256，私密保存且排除 Git。
- `.toolchains/`：工作区内的 ESP-IDF 5.5.3 和编译器。
- `reports/`：构建日志与连接记录。

## 构建和检查

```bash
cargo test --manifest-path rust-bridge/Cargo.toml
cargo build --release --manifest-path rust-bridge/Cargo.toml
source scripts/env.sh
.venv/bin/python scripts/firmware.py build codex
.venv/bin/python -m unittest discover -s tests -v
```

针对已备份的这台设备，运行 `.venv/bin/python scripts/install-companion.py` 可预览，加 `--install` 才会实际安装。刷写前先停止桥接程序。安装器核对设备序列号和备份哈希，并在应用写入前后校验引导程序／分区表／身份数据。

验证后的合并固件为 `firmwares/codex/build/FoloToy-AI-Passport-full.bin`。设备程序复用官方 BSP、240×320 LVGL 屏幕、三键、ES8311 音频和可选电量计。串口帧有长度与范围校验，声音在 UI／按键任务外播放，并显示数据过期和断连状态。

## 原设备与恢复

原固件为 `trae_card 1.0.2`，ESP-IDF 5.5.3，ESP32-C3 revision 1.1，8 MB Flash。原分区包含图片／音频资源和 `0x356000` 处的设备身份，没有 Recovery 分区；备份的 `0x700000` 处也没有 ESP 镜像魔数，不能假定这台设备已经支持新版模板的“开机长按上键五秒恢复”。

针对本机，安装时只写 `0x10000` 开始、最多 `0x300000` 字节的应用分区，保留原引导程序、分区表、设备身份和资源。不要清空 Flash。完整备份含设备身份数据，请只在本地保存。显式运行 `scripts/restore-original.py` 可以还原原应用分区；实际执行还原前，不能声称恢复路径已经过真机验证。

[官方开发指南](https://ai-passport.folotoy.cn/guides/create-your-own-play/) · [Codex app-server API](https://learn.chatgpt.com/docs/app-server)

USB 接管的实机回归命令为 `.venv/bin/python scripts/test-usb-handover.py`（先停止桥接并清空未读提醒，保持 USB 连接且已完成 BLE 配对）。测试使用临时数据库，先建立 BLE，再暴露串口路径，验证 USB 接管时主动断开 BLE，且之后保持断开，不生成测试提醒。完成后重新启动正式监控。

顶部状态栏分隔线已移除。右上方展示纯文字重置卡数量，下方展示重置时间，两组均右对齐，使用灰色标题和深黑色 16 px 粗体数值，不带背景框或装饰。只读数量来自 `account/rateLimits/read.rateLimitResetCredits.availableCount`，复用已有 60 秒轮询，与付费余额无关。未知或过期时显示 `--`，确认无卡时显示 `0`，不增加兑换操作。CDXM 在末尾追加可选数量字段；旧元数据默认未知。

首屏以静态 270 度开口圆环展示额度，百分比居中、重置倒计时放右侧，下方展示七行每日用量，不再显示周汇总。每行包含 MM/DD 日期、比例横条和右对齐的简写用量。日期、数字和单位统一采用 13 px 抗锯齿字体，行距 18 px。最新日期在最上方；横条统一使用橙色，日期不再单独高亮。缺失桶显示 `--` 且不画条；明确零值显示 `0`。七个日历日截至不晚于 Mac 日期的最新已报告日；过期和跨日清除旧数据等待刷新。保持五分钟采集。CDXM 传输归一化用量、每日简写数值与 MM/DD 标签，仍接受旧版仅日期数字的标签。单个绘图对象直接绘制，不新增帧缓冲或动画任务。

24 小时内重置倒计时保留分钟精度，例如 `3h 07m` 或 `59m`。
完成提醒采用标题优先布局：小状态勾、最多三行左对齐半粗体标题，下方细分隔线隔开文件夹图标、上下排列的项目／主机名和右对齐耗时。3200 字节提醒位图包含 168×60 标题及两块 84×16 元数据区域，不新增像素缓冲；桥接与固件需一起升级。

[重置卡和连接状态操作说明](docs/usage.zh_CN.md#重置卡与连接页)

[多固件工作区：新建、构建与安装](docs/firmware-workspaces.zh_CN.md)
