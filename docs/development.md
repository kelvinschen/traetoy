[简体中文](development.zh_CN.md) · [Home](../README.md)

# Developer guide

## Architecture

```text
Passport.app (Swift / AppKit)
  ├─ launchd lifecycle requests
  └─ Unix socket owner + status subscription
       └─ Rust runtime
           ├─ Codex module: local/SSH collection, SQLite, rendering
           └─ device: USB/BLE, identity/capability negotiation
                └─ ESP32-C3 firmware
```

Rust owns local and remote Python hook receivers, with SSH carrying remote streams. Independent account RPC supplies quota/tokens without affecting task health. See [Hooks](hooks.md).

Event definitions live in independent hooks.json files. The bridge does not read Codex SQLite, poll task state or scan historical sessions; it watches final records only in active files supplied by new hooks. Final-record compatibility is tested against Codex 0.153.4 and needs regression checks after upgrades.

## Code map

Attention comes from PermissionRequest and input-tool PreToolUse hooks; the first live edge can notify. PostToolUse clears synchronous waiting; async questions remain until new user input or turn termination. waiting-alert-v1 gates kind 3. Device OK only dismisses a notification. The shared C parser defaults to kinds 1–2; Codex Pet enables kind 3 through COMPANION_ALERT_KIND_MAX=3.

| Path | Responsibility |
| --- | --- |
| `rust-bridge/src/runtime.rs`, `codex.rs`, `control.rs` | Lifecycle, collection module, local control |
| `hooks.rs`, `scripts/codex-hooks/hook.py` | Local/SSH hooks and final-record watching |
| `account.rs`, `rpc.rs` | Independent quota and account usage RPC |
| `state.rs` | Online transactions, sequences, counters |
| `display.rs` | Quota, token, reset-card and display conversion |
| `render.rs`, `text.c` | CoreText bitmap rendering |
| `device.rs`, `ble.rs`, `ble_macos.m` | Transport and authentication; Codex transactions live in `codex_wire.rs` |
| `firmwares/codex/main/` | Firmware UI, protocol, refresh and alert state machines |
| `scripts/bridge-service.sh` | LaunchAgent lifecycle |
| `scripts/install-companion.py` | Protected app-only installer for the backed-up device |
| `tests/` | Compatibility bridge and integration behavior tests |

Rust filenames above are relative to `rust-bridge/src/`. Remote/account configuration is in `config/bridge.json`; private pairing is in `config/ble-device.json`; durable state is in `reports/companion-state.sqlite3`. Never publish pairing keys, original backups or unsanitized logs.

## Environment and build

The current host is Apple Silicon macOS. The bridge requires Rust, CoreText/CoreBluetooth and a C/Objective-C compiler. Firmware targets ESP32-C3 using ESP-IDF 5.5.3; workspace toolchains live in `.toolchains/`. The existing workspace has `.venv`; to recreate tool dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cargo test --manifest-path rust-bridge/Cargo.toml
cargo clippy --manifest-path rust-bridge/Cargo.toml -- -D warnings
cargo build --release --manifest-path rust-bridge/Cargo.toml
```

After updating the binary, run `./scripts/bridge-service.sh restart`. Before migrating an old background process, stop it, then run `./scripts/bridge-service.sh install`. Reinstall after moving the workspace because launchd uses absolute paths. Do not copy SSH agent sockets or keys into its configuration.

## Foreground and device diagnostics

Receiver connections, disconnections and active-file loss are logged in reports/bridge.log. Reconnect backoff is bounded at 30 seconds and reconnects only the receiver, without task restoration. Logs omit prompts, tool arguments and answers.

Receiver pulses update health every five seconds, including during prolonged idle. Broken streams, expired heartbeats and lost active files mark the source unhealthy. Account request errors are logged independently.

Stop launchd before taking the device lock:

```bash
./scripts/bridge-service.sh stop
./rust-bridge/target/release/passport-bridge --workspace "$PWD" --log-file
# Ctrl+C, then restore monitoring:
./scripts/bridge-service.sh start
```

Rust supports `--local-only`, `--remote ALIAS`, `--thread ID`, and `--transport usb|ble|auto`. Use foreground mode for diagnostic overrides instead of changing production transport policy. `--dry-run` uses temporary state by default. Consult `--help` and `runtime.rs` for arguments.

Device checks temporarily replace task pages. Dismiss unread alerts and stop production first:

```bash
./scripts/bridge-service.sh stop
./rust-bridge/target/release/passport-bridge --workspace "$PWD" --device-check --transport usb
./scripts/bridge-service.sh start
```

Use `--transport ble` for wireless checks. ACK validation does not establish screen readability, button behavior or sound quality.

## Pairing and account source

Initial pairing requires USB and compatible installed firmware:

```bash
./scripts/bridge-service.sh stop
.venv/bin/python scripts/pair-ble.py
./scripts/bridge-service.sh start
```

Pairing keys are provisioned over USB and stored privately in device NVS and local configuration. They survive power loss; normal reconnection does not require pairing.

Before enabling an account source or after changing account/subscription, run `.venv/bin/python scripts/verify-account-source.py HOST_ALIAS`, substituting the configured alias. This one-time check starts and closes a temporary local App Server; resident monitoring does not. Investigate identity mismatches rather than bypassing validation.

## Protocol semantics

`CDXP` carries title bitmaps, `CDXL` commits the task list, and `CDXM` carries usage/dates/durations/reset-card metadata. State packets and ACKs complete display transactions. Retries must reuse the same immutable transaction and sequence, never combine new titles with old metadata.

Device ACK means received; user acknowledgement belongs to its alert stack. Disconnect clears task state without successful completion or historical replay. Existing device unread alerts remain device-managed.

Only new notifications after device connection are accepted. Offline events are dropped before persistence. Disconnect and fresh identity handshakes discard pending transactions. Existing SQLite remains an internal implementation for online delivery transactions, sequence numbers and counters; old pending rows are skipped and never restored after reconnect.

Quota is `100 - usedPercent`. Reset cards come from `rateLimitResetCredits.availableCount`, independently of paid credit balance. Seven daily rows end at the latest reported date and display newest first; missing and zero remain distinct. Duration covers the current response turn, including tools and waits, not the lifetime of the conversation.

## Firmware workflow

Read firmware [AGENTS.md](../firmwares/codex/AGENTS.md) and its task-specific routes before editing. Respect LVGL locking, nonblocking button callbacks and cleanup. UI changes need real-screen acceptance.

Activate the toolchain in Bash and run validation:

```bash
bash
source scripts/env.sh
.venv/bin/python scripts/firmware.py build codex
.venv/bin/python -m unittest discover -s tests -v
```

**This board retains its original partition table and lacks the template Recovery partition.** Never erase the chip or flash a merged image at zero. The private original 8 MB backup contains device identity.

```bash
./scripts/bridge-service.sh stop
.venv/bin/python scripts/install-companion.py            # Validate and preview
.venv/bin/python scripts/install-companion.py --install  # Write application
./scripts/bridge-service.sh start
```

The installer extracts the application from verified `firmwares/codex/build/FoloToy-AI-Passport-full.bin`, writes only at `0x10000` with a 3 MB limit, and verifies backup integrity, serial identity, bootloader/partition table and `cardid`. Do not bypass checks; this is not a generic installer for unbacked-up boards. Original-app restoration is a separate explicit `scripts/restore-original.py --restore` operation.

## Performance and acceptance

Hardware: ESP32-C3 at 160 MHz, 400 KB SRAM, 8 MB Flash, no PSRAM, 240×320 display. Watch LVGL objects, title bitmaps, transport buffers and task snapshots.

Keep incremental file reads, bounded queues and small SQLite caches. Unchanged text skips rasterization/transmission; firmware redraws only visible changes without continuous animation. Defaults are 3-second device state, 5-minute quota/reset-card calibration plus live task quota snapshots and 60-minute tokens; reset cards add no separate poll. Token usage is fetched on service startup and cached for up to 75 minutes, allowing 15 minutes of refresh delay before hiding stale values. Usage from a previous calendar day remains hidden.

Measure the entire process tree:

```bash
.venv/bin/python scripts/measure-resources.py --seconds 40 --output reports/resources.json
```

RSS/CPU includes Rust and SSH; summed RSS may double-count shared pages. Device ACK `heap` is current free heap, while `min_heap` is the low-water mark since boot. Stress-test lows are not steady-state usage.

Report build, host tests, device protocol tests and unverified items separately. Historical measurements and concept images are not evidence of current performance or actual rendering. Documentation-only changes need command/link checks, not device flashing.

## Auxiliary information pages

`rust-bridge/src/info.rs` extracts cards from existing quota responses and health from `State.sources`. Firmware `companion_info.c` implements bounded ASCII parsing/navigation; `companion_info_ui.c` shares one LVGL draw object across pages. Fixed Chinese labels use a 16 px Noto Sans CJK subset.

The new frame is `CDXI|seq|available|quota_age|generation|known|count|timezone|source_count|name|healthy|...|title|status|granted|expires|description|type|...|END`, acknowledged with `CDX_INFO_ACK seq`. The host sanitizes pipes/control characters; credit IDs, credentials and redemption commands are never transmitted. Per-card ASCII limits are title 39, status 15, dates 16, description 159 and type 23, with at most six cards/four sources. Long text is explicitly ellipsized. Dynamic Chinese card copy is not supported; fixed Chinese labels are supported.

Only changed payloads/reconnections trigger auxiliary transmission. The quota-response generation timestamp refreshes freshness even when values remain unchanged. No extra polling is added. USB/BLE self-checks cover missing details, valid cards and duplicate delivery. Upgrade bridge and firmware together.

Completion bitmap layout: 168×60 title followed by 170×16 workspace (3200 packed bytes total). The optional final `CDXM` field carries a bounded 48-character ASCII host; each alert snapshots it independently. Host and duration occupy the next display row. Firmware and bridge must be updated together when this bitmap layout changes.

## Passport menu application

Build with `cargo build --release --manifest-path rust-bridge/Cargo.toml` and `./scripts/build-tray.sh`; install the LaunchAgent using `./scripts/bridge-service.sh install`, then open `macos-app/build/Passport.app`. Swift 6 / AppKit and macOS 13+ are required. The development app is ad-hoc signed and stores its workspace path in its bundle. Keep this path stable; quit before rebuilding or moving it.

`runtime.rs` coordinates lifecycle; `codex.rs` owns collection and durable delivery; `codex_wire.rs` owns Codex frames and bitmap caches; `device.rs` owns transports. `control.rs` serves version-1 newline-delimited JSON operations `status`, `subscribe`, `reconnect`, `stop`. Requests are capped at 4096 bytes, clients at eight, and peers must match the current UID. `reports/control` is mode 0700, sockets 0600. The menu holds an owner subscription. Managed startup allows 30 seconds to attach; owner loss allows ten seconds to reconnect. Foreground diagnostics do not require ownership but retain the same exclusive device lock.

Firmware query: `PASSPORT?|END`; response: `PASSPORT|id|version|protocol|capability,capability|END`. Protocol 1 plus `codex-v1`, `completion-wide-v1`, `info-v1` selects the built-in Codex sender. Appearance IDs do not select code. Unsupported or missing negotiation blocks business frames; reconnect invalidates the identity cache. Firmware retains legacy frame parsers for diagnostic tools.

The app controls launchd through private `backend-start`, `backend-stop`, `backend-force-stop` script actions; users use the public actions. There is no backend RunAtLoad/KeepAlive. Public CLI actions reach the same menu controller over `app.sock`. Do not manually run backend-start without the app: managed ownership will time out.

Validation: Rust tests/clippy, `scripts/test-tray-control.py`, `scripts/test-tray-lifecycle.py`, firmware complete gate, USB/BLE device-check and `scripts/test-usb-handover.py`. `scripts/measure-resources.py` discovers menu/launchd PIDs and descendants and reports RSS, physical footprint, CPU and wakeups separately.

Rollback: quit Passport, disable its login item, restore the matching old Rust binary and protected app firmware from `backups/pre-tray`, then restore `bridge.plist` and the previous launcher. Keep data and pairing in place. Never flash the backup merged image directly across protected regions. Install-script backups are timestamped; they are private and must not be published.

Firmware variants must preserve the shared 115200-baud USB framing and existing encrypted BLE service/authentication contract, including pairing data in NVS, to reuse automatic connection. Capability negotiation does not make an unrelated Bluetooth protocol compatible.

[Firmware workspaces: create, build and install](firmware-workspaces.md)
