[English](CONTRIBUTING.md)

# 贡献指南

感谢你改进 Traetoy。贡献按根目录 MIT 许可证提交。请不要提交自己无权再分发的素材。

## 提交拉取请求前

- 阅读 README.zh_CN.md、PRIVACY.zh_CN.md、NOTICE 和 ASSET_PROVENANCE.zh_CN.md。
- 维护的文档必须保持英文与简体中文配对。
- 不要提交凭证、配对密钥、私有 SSH 配置、备份、设备身份、用户数据或未脱敏日志。
- 保持 USB/BLE 兼容性约定；不要擦除设备或直接刷写合并镜像。

## 验证

从仓库根目录运行相关检查：

    cargo test --manifest-path rust-bridge/Cargo.toml
    .venv/bin/python -m unittest discover -s tests -v
    .venv/bin/python scripts/firmware.py build codex
    .venv/bin/python scripts/firmware.py build codex-pet

分别报告 Build、Host tests、Device tests 和 Unverified。构建成功不代表真机测试成功。

## 拉取请求

每个拉取请求保持聚焦。说明用户可见行为、兼容性影响、已执行验证和未验证的硬件工作。安全漏洞请走安全报告流程，不要公开提交 issue。
