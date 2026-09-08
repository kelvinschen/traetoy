[简体中文](README.zh_CN.md)

# AI Passport shared board support

MIT-licensed board and recovery source extracted from the existing FoloToy AI Passport checkout; see `LICENSE`. The encrypted BLE transport is shared application support. Keep its UUIDs and NVS namespace stable to preserve existing pairing.

- `components/bsp`: display, input, audio, battery and buses.
- `components/passport_ble`: bounded authenticated BLE transport; no Codex UI or business processing.
- `bootloader_components`: permanent recovery entry hook. ESP-IDF enumerates this directory under each firmware project, so workspace creation installs a relative directory link.
- `sdkconfig.defaults`, `partitions.csv`: copied into newly created workspaces; subsequent workspace configuration is independent.
- `tools/verify_firmware.py`: validates image layout, application size and recovery hook.

See the [workspace guide](../../../docs/firmware-workspaces.md). Validate all consumers after changing shared code.
