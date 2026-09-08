[English](README.md)

# AI Passport 共用板级支持

板级和恢复源码从现有 FoloToy AI Passport 仓库提取，使用 MIT 许可，见 `LICENSE`。加密 BLE 传输作为共用应用支持，保留其 UUID 和 NVS 命名空间，避免破坏现有配对。

- `components/bsp`：屏幕、按键、音频、电池和总线。
- `components/passport_ble`：有边界校验和认证的 BLE 传输，不包含 Codex UI 或业务处理。
- `bootloader_components`：永久恢复入口。ESP-IDF 会枚举各固件项目下的这个目录，因此创建工作区时添加相对目录链接。
- `sdkconfig.defaults`、`partitions.csv`：创建时复制到新工作区，后续各自独立修改。
- `tools/verify_firmware.py`：校验镜像布局、应用大小和恢复入口。

详见[工作区指南](../../../docs/firmware-workspaces.zh_CN.md)。修改共用代码后验证全部引用方。
