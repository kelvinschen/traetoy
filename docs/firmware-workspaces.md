[简体中文](firmware-workspaces.zh_CN.md)

# Firmware workspaces

Passport has one shared desktop application and multiple independent firmware applications:

```text
macos-app/                       Swift menu bar application
rust-bridge/                     Shared device owner and built-in Codex module
firmwares/codex/                 Existing Codex firmware
firmwares/<name>/                New independent firmware application
shared/boards/ai-passport/       BSP, BLE transport, recovery hook, validation and defaults
templates/firmware-blank/        Blank application template
scripts/                        Shared development and installation tools
config/  reports/  backups/      Existing configuration, runtime state and backups
```

## Create and build

Run from the project root:

```bash
.venv/bin/python scripts/firmware.py list
.venv/bin/python scripts/firmware.py new my-clock
.venv/bin/python scripts/firmware.py build my-clock
```

`new` creates an independent application, not a copy of Codex screens or business logic. Edit its `main/main.c` and `main/firmware_identity.h`. Each workspace owns its configuration, partitions, dependency lock and build output. Names are lowercase slugs; existing directories are never overwritten. Build selection is explicit: there is no global “active firmware”.

The blank application displays a label and answers the shared USB/BLE identity protocol. Its BLE receive callback queues work; UI changes require the BSP LVGL lock. Existing pairing keys remain in device NVS. BLE identifiers and the `codex_ble` NVS namespace retain their historical names for pairing compatibility. Provision a previously unpaired device using the existing supported Codex firmware first; the blank template does not implement USB key provisioning or Codex functionality.

`build` uses a fresh temporary build directory and verifies the merged image and recovery layout. Codex also runs its complete static and host-test gate. A workspace-specific SHA-256 validation receipt is written alongside the image. A failed build removes the receipt; installation rejects an absent or mismatched receipt.

## Install deliberately

Stop the shared service before using the USB port. Use the application menu or `scripts/bridge-service.sh stop`. Keep the original backed-up device connected and awake:

```bash
.venv/bin/python scripts/install-companion.py --workspace my-clock
.venv/bin/python scripts/install-companion.py --workspace my-clock --install
scripts/bridge-service.sh start
```

The first command previews. The second writes only the application after checking the original backup, device identity and protected regions, then verifies the protected regions again. Never flash a merged image directly or erase the device. Without `--workspace`, the installer selects `codex` for backward compatibility; it still requires a validation receipt from the new build command.

## Reuse the desktop application

The tray and bridge remain at their existing root paths, with the same launchd registration, configuration, database and pairing data. Changing or creating a firmware workspace does not change the running device or install another tray.

On each connection the bridge queries firmware identity, version, protocol and capabilities. A new appearance implementing the existing Codex contract can declare the corresponding capabilities and reuse the built-in Codex module. A blank application declares only `passport-core-v1`: the tray can show identification and manage the service, but currently reports it as unsupported and sends no Codex payloads. New business capabilities require a corresponding built-in Rust module; this is not dynamic plugin loading or automatic support for arbitrary firmware protocols.

## Shared code and repository boundaries

Codex uses relative links to the shared BSP, bootloader hook, BLE sources and verifier, preserving existing source/test paths. New workspaces use shared ESP-IDF components directly. Configuration and partition defaults are copied on creation, not linked. Changes in shared source affect every firmware: validate Codex and an independent blank workspace after SDK changes.

The project root is the single Git repository on branch `main`. All firmware and shared source files are tracked directly, without nested repositories or submodules. The previous Codex repository's Git metadata and available history are preserved locally at `backups/git-history/codex.git`; this private backup is excluded from commits. To inspect its original history, use `git --git-dir=backups/git-history/codex.git log` from the project root.

Runtime reports, backups, pairing credentials, local `config/bridge.json`, toolchains and build products are ignored. `config/bridge.example.json` supplies a local-only configuration example; copy it to `config/bridge.json` on a new machine and configure SSH aliases as needed. Existing local configuration is unchanged. Build within the complete root checkout so every firmware can find the shared SDK. Old build caches may contain earlier paths; use the fresh-build wrapper above. Historical local reports retain their original path records.
