[简体中文](AGENTS.zh_CN.md)

# Passport workspace guidelines

- For a new firmware application, use `scripts/firmware.py new <name>`. Start from the blank template unless the user explicitly requests an existing firmware variant. Develop within `firmwares/<name>`.
- Keep `macos-app` and `rust-bridge` shared. Select build/install workspaces explicitly; creating a workspace must not change the live device or desktop service.
- Read `docs/firmware-workspaces.md`. For Codex firmware changes also read `firmwares/codex/AGENTS.md` and its routed instructions.
- Shared board source is in `shared/boards/ai-passport`; changes affect all consumers. Validate Codex and a blank workspace after shared changes. Keep per-firmware configuration independent.
- Preserve device recovery, identity, pairing and backups. Use the protected app-only installer; never erase or directly flash merged images.
- Validate via `.venv/bin/python scripts/firmware.py build <name>`. Report Build, Host tests, Device tests and Unverified separately; successful compilation is not a hardware test.
- Keep maintained documentation paired in English and Simplified Chinese with reciprocal links. Preserve unrelated user changes and nested Git history.
