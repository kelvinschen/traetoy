[English](README.md)

# Traetoy

Traetoy 是面向 FoloToy AI Passport 硬件的独立开源配套软件与固件。它包含 ESP32-C3 固件、macOS 菜单栏应用和本地 Rust 桥接服务，可通过 USB 或经认证的 BLE 显示 Codex 任务与账号状态。

Traetoy 不由 FoloToy 或 OpenAI 发布、关联或背书。它为现成零售设备提供软件兼容性；不公开硬件设计、原始设备备份或产品视觉素材。

## 包含的内容

- Codex 仪表盘和 Codex Pet 固件工作区；
- AI Passport 显示、音频、输入、电池、分区、恢复和 BLE 约定的共用板级支持；
- macOS 菜单栏应用、Rust 桥接、本机/SSH hook 接收器和主机测试；以及
- 仅源码的构建与验证工具。

首次公开发布不包含预编译固件。不要擦除设备或直接刷写合并镜像。只有审查安装器的设备和备份检查后，才使用受保护安装器。

## 从源码构建

配套应用需要 macOS，固件构建需要 ESP-IDF 5.5.3。创建本地 Python 环境、安装固定的主机依赖后，运行与你的改动相关的检查：

~~~sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cargo test --manifest-path rust-bridge/Cargo.toml
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/firmware.py build codex
.venv/bin/python scripts/firmware.py build codex-pet
~~~

环境配置与验证详见[开发指南](docs/development.zh_CN.md)、[固件工作区指南](docs/firmware-workspaces.zh_CN.md)和 [Hooks 指南](docs/hooks.zh_CN.md)。配置可选 SSH 主机前，将 config/bridge.example.json 复制到被 Git 忽略的本地路径 config/bridge.json。

## 隐私与安全

桥接会处理任务标题、项目标签、耗时、额度摘要和本地设备状态；设计上不会把提示词、工具参数、回答或账号凭证发送到设备。启用远端主机或连接共享设备前，请阅读 [PRIVACY.zh_CN.md](PRIVACY.zh_CN.md)。

绝不要提交本地配置、BLE 配对材料、设备备份、数据库文件、报告或日志。私密报告漏洞请参阅 [SECURITY.zh_CN.md](SECURITY.zh_CN.md)。

## 许可证、来源和已知素材

原创 Traetoy 源码使用 MIT 许可证，详见 [LICENSE](LICENSE)。FoloToy 板级支持和固件基线保留上游 MIT 声明；字体和 vendored 依赖保留各自原始声明。

[NOTICE](NOTICE) 和 [ASSET_PROVENANCE.zh_CN.md](ASSET_PROVENANCE.zh_CN.md) 记录全部素材来源。仓库有意保留尚未找到再分发许可的 Codex 商标图标和部分任天堂游戏音频。它们不是 Traetoy 原创素材，不被描述为已授权，并可能在权利人提出要求后需要移除。

## 贡献

参与前请阅读 [CONTRIBUTING.zh_CN.md](CONTRIBUTING.zh_CN.md)、[CODE_OF_CONDUCT.zh_CN.md](CODE_OF_CONDUCT.zh_CN.md) 和 [SUPPORT.zh_CN.md](SUPPORT.zh_CN.md)。贡献按根 MIT 许可证提交，且不得包含私密数据或无权分发的素材。
