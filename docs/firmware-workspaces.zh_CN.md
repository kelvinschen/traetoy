[English](firmware-workspaces.md)

# 多固件工作区

Passport 使用一套桌面应用，管理多个独立固件项目：

```text
macos-app/                       共用 Swift 菜单栏
rust-bridge/                     共用设备管理与内置 Codex 模块
firmwares/codex/                 现有 Codex 固件
firmwares/<名称>/                新开发的独立固件
shared/boards/ai-passport/       共用 BSP、BLE、恢复入口、校验器和默认配置
templates/firmware-blank/        空白应用模板
scripts/                        共用开发与安装工具
config/  reports/  backups/      原有配置、运行数据和备份
```

## 新建与构建

在项目根目录执行：

```bash
.venv/bin/python scripts/firmware.py list
.venv/bin/python scripts/firmware.py new my-clock
.venv/bin/python scripts/firmware.py build my-clock
```

新建的是独立应用，不会复制 Codex 页面或业务。修改该目录的 `main/main.c` 和 `main/firmware_identity.h` 即可开发。每个工作区有独立配置、分区表、依赖锁和产物。名称使用小写字母、数字及连字符，已有目录不会被覆盖。构建时明确指定工作区，没有全局“当前固件”的隐式状态。

空白应用展示一个标签，并响应共用 USB/BLE 身份查询。BLE 回调将工作放入队列，修改 UI 需要持有 BSP 的 LVGL 锁。设备 NVS 中原有配对密钥继续使用；BLE 标识及 `codex_ble` 命名空间保留历史名称，避免破坏配对。空白模板未实现 USB 密钥配置和 Codex 业务；全新未配对设备应先通过现有 Codex 固件完成配对。

构建使用全新临时目录，校验合并镜像及恢复分区约定。Codex 还运行完整静态检查与主机测试。成功后写入该工作区的 SHA-256 校验凭据；构建失败会移除凭据，安装工具拒绝缺失凭据或哈希不匹配的产物。

## 明确选择安装对象

使用 USB 前，先通过菜单栏或 `scripts/bridge-service.sh stop` 停止共用服务。保持原来已经备份的设备连接且唤醒：

```bash
.venv/bin/python scripts/install-companion.py --workspace my-clock
.venv/bin/python scripts/install-companion.py --workspace my-clock --install
scripts/bridge-service.sh start
```

第一条仅预览；第二条校验原始备份、设备身份和保护区域后，只写入应用区域，并再次校验保护区域。禁止直接刷入合并镜像或擦除设备。为兼容旧命令，省略 `--workspace` 时选择 `codex`，但仍需先用新的构建命令生成校验凭据。

## 复用桌面应用

菜单栏、bridge 保持根目录原路径，launchd 注册、配置、数据库和配对数据不变。创建工作区不会改变正在运行的设备，也不会安装另一套菜单栏。

每次连接后，bridge 查询固件身份、版本、协议和能力。实现现有 Codex 协议的新外观固件，可以声明对应能力，复用内置 Codex 模块。空白固件只声明 `passport-core-v1`：菜单栏可展示识别信息、管理服务，但目前会报告业务不兼容，不发送 Codex 数据。新业务能力需要增加对应的 Rust 内置模块；这不是动态插件加载，也不会自动支持任意固件业务协议。

## 共用代码与仓库边界

Codex 通过相对链接引用共用 BSP、恢复入口、BLE 源码及校验器，保持原有源码和测试路径。新固件直接引用共用 ESP-IDF 组件。配置和分区表在创建时复制，后续各自独立。修改共用代码会影响所有固件，需要同时验证 Codex 和独立空白工作区。

项目根目录现在是唯一 Git 仓库，使用 `main` 分支。固件及共用源码直接纳入版本管理，不使用嵌套仓库或子模块。原 Codex 仓库的 Git 元数据及现有历史保存在本地 `backups/git-history/codex.git`，不纳入提交。可从根目录执行 `git --git-dir=backups/git-history/codex.git log` 查看原历史。

运行报告、备份、配对密钥、本机 `config/bridge.json`、工具链及构建产物均被忽略。`config/bridge.example.json` 提供仅使用本机的配置示例；新机器可复制为 `config/bridge.json`，按需配置 SSH 别名。原有本机配置不变。构建需要完整根仓库，以便各固件引用共用 SDK；旧缓存可能包含早期路径，使用上述全新构建入口。历史本地报告保留当时的路径记录。
