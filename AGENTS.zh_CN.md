[English](AGENTS.md)

# Passport 工作区约定

- 新开发固件使用 `scripts/firmware.py new <名称>`。除非用户明确要求基于现有固件变体开发，否则从空白模板开始，在 `firmwares/<名称>` 内实现。
- 共用 `macos-app` 和 `rust-bridge`。构建、安装明确指定工作区；创建工作区不得改变正在运行的设备或桌面服务。
- 阅读 `docs/firmware-workspaces.zh_CN.md`。修改 Codex 固件还需阅读 `firmwares/codex/AGENTS.md` 及其路由文档。
- 共用板级源码位于 `shared/boards/ai-passport`，修改会影响全部引用方。修改后同时验证 Codex 和空白工作区，保持各固件配置独立。
- 保留设备恢复区、身份、配对和备份。使用受保护的应用区安装工具，禁止擦除或直接刷合并镜像。
- 使用 `.venv/bin/python scripts/firmware.py build <名称>` 验证；分别报告 Build、Host tests、Device tests、Unverified，编译通过不等于硬件测试通过。
- 维护中英文配对文档及互链，保留无关用户修改及嵌套 Git 历史。
