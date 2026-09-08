[简体中文](README.zh_CN.md)

# Passport workspace

[User guide](docs/usage.md) · [Developer guide](docs/development.md)

A shared macOS application and Rust bridge, with independent firmware workspaces. The existing Codex dashboard lives in `firmwares/codex`. Create a new application with `.venv/bin/python scripts/firmware.py new my-clock`; see [firmware workspaces](docs/firmware-workspaces.md).

The following sections describe the included Codex firmware.

A Mac BLE/USB bridge and an ESP32-C3 dashboard for Codex account quota and local/SSH task completion notifications. No Wi-Fi or API key is needed. The Mac must remain awake with the bridge running and the device connected.

The companion redraws only when displayed values change; packet sequence numbers and seconds within a displayed minute do not trigger redraws. Button and packet events wake the application loop directly. After one minute without a button press or a new alert, backlight duty drops from 75% to 35%; input or a new alert restores 75% immediately. The screen remains visible and monitoring continues. Battery charge is sampled every 30 seconds. BLE fragments use up to 244 bytes when the negotiated MTU permits.

[Performance and power verification](reports/device-performance-result.md).

After one hour without a new alert, turn the backlight completely off while monitoring continues. Manual wake starts a fresh one-hour window; ordinary data updates and awake navigation do not extend it. Any function key wakes without navigating; a new completion alert wakes automatically and plays its sound. Alert visible-time countdowns and screen redraws pause while off. The dedicated left power button controls hardware power and is not exposed as a software key.

## BLE connection (Rust v0.4)

The Rust bridge now supports BLE and USB. The default `auto` mode prefers an available USB data connection and uses the paired BLE device when USB is unavailable; task/account collection is unchanged. Both the Mac and device must remain powered and awake. BLE does not require Wi-Fi or a company network login.

One-time setup, with the device connected by USB:

```bash
.venv/bin/python scripts/bridge-service.py stop
.venv/bin/python scripts/pair-ble.py
.venv/bin/python scripts/bridge-service.py start
```

Unlock the Mac and allow the first Bluetooth permission request. If access was denied, enable it in System Settings → Privacy & Security → Bluetooth for the application named by macOS, then restart the bridge. No pairing in macOS Bluetooth Settings is required: the private application key is provisioned over USB. It is stored in `config/ble-device.json` with mode 0600 and in device NVS; do not share that file. Re-running provisioning preserves the existing key.

Auto mode keeps one transport at a time. Available USB takes priority and closes any existing BLE session before opening the serial port. While USB works, the bridge does not connect, scan or keep alive Bluetooth. Without usable USB it connects the paired BLE device, and checks for USB every three seconds. The header shows only the currently active USB or Bluetooth icon, in orange. Opening USB preserves DTR/RTS to avoid resetting the device. Switching transports clears the bitmap cache and retries the pending transaction. Failed BLE attempts have a five-second cooldown; a failed USB exchange backs off that endpoint for fifteen seconds. Pairing survives power loss, while unread alerts remain in RAM.

Use `start --transport usb` to force USB or `start --transport ble` for BLE only. Stop the service first when changing modes. The Python fallback remains USB only. The bridge does not install another App Server or a remote BLE helper.

With the service stopped and unread alerts cleared, `rust-bridge/target/release/passport-bridge --device-check --transport usb` exercises 0/1/2/16 task frames and replacement. Use `--transport ble` for the same wireless test. `--ble-check` tests authenticated round trips, replay/tamper rejection and reconnection without creating task alerts. These diagnostics own the same exclusive device lock; the display test temporarily replaces visible task data. Restart normal monitoring afterward.

See the [BLE design and verification report](reports/ble-implementation-result.md) for the protocol, measured resources and pending hardware acceptance.

## Run

Manage the bridge with the native Passport menu app. Opening it starts the service; stopping keeps the menu app, quitting stops the backend. Login startup is independent. See the [user guide](docs/usage.md) and [developer guide](docs/development.md) for installation and operation.

```bash
open macos-app/build/Passport.app
./scripts/bridge-service.sh status
./scripts/bridge-service.sh stop
./scripts/bridge-service.sh start
./scripts/bridge-service.sh quit
```

Foreground mode:

```bash
./scripts/start-companion.sh
# Display only one task across configured hosts:
./scripts/start-companion.sh --thread YOUR_TASK_UUID
# Inspect live data without touching USB or production state:
./scripts/start-companion.sh --dry-run --once
# Stop with Ctrl-C.
```

Use `.venv/bin/python scripts/restore-original.py` to verify the backup without writing; add `--restore` only when you want the original identity-card application back. Stop the bridge first.

The PAPER METER interface uses the official Codex icon, with no sound toggle or bottom key hints. Press OK on the home screen to reopen unread alerts first, or view running task titles when none remain; UP/DOWN selects a task and changes pages; hold OK to return home. OK confirms the newest unread alert and shows the next one; after the last alert it restores the previous page. Hold OK to return home without confirming. New alerts immediately appear on top; the header check badge shows the unread count on every page. The device keeps the newest eight packed snapshots in RAM; at capacity it evicts the oldest, and restarting the device clears the stack. Each alert is automatically confirmed after 30 seconds of accumulated visible time; a newer alert or returning home pauses its timer. After the latest alert expires, the next resumes its remaining time; after the last, the original page returns. Recent duplicate transmissions do not create another alert or replay sound. The completion page uses a small status check above up to three left-aligned semibold title lines. A thin divider separates the bottom orange folder icon, stacked project/host labels, and right-aligned duration. The 3200-byte alert tile holds a 168×60 title and two 84×16 metadata regions without extra pixel buffers; bridge and firmware must be upgraded together. The title/workspace image and duration are captured at completion and remain fixed through background updates. Completion sound stays enabled at 100% codec volume. The header shows only the active USB or BLE transport in orange. The battery is a taller 32 × 16 pixel outline with the charge number inside, using a 13 px digit font without a percent sign; the filled portion uses contrasting text. There is no dedicated connection-text row. The default is local root tasks plus the SSH aliases in `config/bridge.json` (currently `devbox`). Each completed response turn produces a notification. Interruptions display “Task stopped” and do not increase the completion count. Cloud tasks are not monitored. The first connection establishes a baseline without historical alerts; later restarts and reconnects backfill terminal turns since the saved checkpoint, including tasks archived in the meantime. The state database is private and workspace-local. Device delivery is distinct from user acknowledgement; the device still owns its eight-item RAM stack.

Quota reuses the existing remote App Server selected by `account_host` in `config/bridge.json`, over the same SSH connection as tasks. It is read every 60 seconds using `account/rateLimits/read`. Remaining percentage is `100 - usedPercent`; windows are labeled using their actual duration. Missing windows are hidden; data expires after 180 seconds. Device heartbeat expires after 20 seconds. The device receives only percentages, reset times, counts and task-title bitmaps. Account credentials and conversations are never sent to the device. Chinese titles are rendered with macOS CoreText and Arial Unicode, using 20 px text and four grayscale alpha levels. The list holds up to 16 running tasks, two per page; each row shows the project, up to two title lines, and elapsed time. Projects come from the task working directory; Git linked worktrees and repository subdirectories resolve to the original repository name, with the directory name as fallback. Project lookups are cached; unchanged display content skips rasterization and bitmap transmission.

Remote tasks use a persistent SSH connection to the existing `codex app-server proxy`, with WebSocket JSON-RPC. No custom collector is installed remotely. `thread/list`, `thread/read` and paginated `thread/turns/list` provide titles, working directories, runtime states and turn timing; `itemsView=notLoaded` avoids fetching conversation items. Remote project names prefer `project/list`; if absent, the remote cwd basename is used with the SSH alias. The Mac never runs local Git against a remote path. Thread discovery runs about every ten seconds; active tasks are checked about every three seconds. This version deliberately uses read-only polling: attaching a new connection does not establish that it receives all turn-completion events. `optOutNotificationMethods` suppresses unneeded notification streams only on the monitor connection; desktop connections are unaffected.

On this Mac, the desktop App Server uses stdio and has no attachable control socket. Local tasks therefore retain the lifecycle-file compatibility source (`task_started`, `task_complete`, `turn_aborted`), tested with CLI 0.153.2. Rust reads title/cwd metadata directly from local `state_*.sqlite` using a read-only connection; it starts no additional local App Server. Both the lifecycle files and this database are version-dependent compatibility interfaces. Unchanged files are skipped, inactive old files retire from the watch set, and alert deduplication is durable in SQLite. A crash without a terminal event can leave a local task unresolved; it is not reported as completion.

Source workers cannot block device refresh. An offline source retains its last task snapshot, freezes elapsed time, and marks project labels with `?`; it is never converted to a successful completion. SQLite stores source checkpoints, pending deliveries and terminal-turn identities (host/thread/turn); delivered identities are retained for 30 days. Pending deliveries are not discarded. Cross-restart retries reuse their saved sequence. Titles, metadata and state form an immutable device retry transaction. A device ACK means received, not read; exactly-once delivery across arbitrary device resets or firmware dedup-cache eviction is not guaranteed.

Token activity comes from the official `account/usage/read` endpoint every five minutes. The device shows the latest reported day and the sum of returned daily buckets in the seven-calendar-day range ending on that date, in K/M/B tokens. The date is the service bucket date, not an assumed local timezone. Missing or delayed metrics show `--`; missing current-day data is never shown as zero. These are token activity counts, not remaining subscription credits or a bill. The quota reset window and token seven-day window are independent. A successful response can lag behind current usage; the displayed date makes that visible.

Task timing covers the current response turn, including tool time and waits. Running duration uses the recorded start time; completed duration prefers native `durationMs` (local compatibility: `duration_ms`), with timestamp subtraction as fallback. Unknown durations are hidden; durations show `<1m`, `3m`, or `1h 12m`, with no prefix or seconds. It is not lifetime elapsed time across every turn of a task.

The bridge skips unchanged session files before opening them and filters lifecycle records before parsing JSON. It reads appended bytes only after its startup baseline, tracks title content, and rasterizes/transmits only when changed. Device state/timing updates about every three seconds, quota every minute, account token activity every five minutes. The Mac runs the native menu app, Rust service and one SSH process per configured remote; no resident Python, Node or extra local App Server. Rust uses a bounded channel, incremental reads, restricted SQLite caches and a small C shim for CoreText. It does not invoke a model to monitor tasks. Measure the full bridge process tree with `.venv/bin/python scripts/measure-resources.py --seconds 40 --output reports/resources.json`; RSS may count shared pages more than once; physical footprint is reported separately.

Before enabling an account source, verify it matches the local account: `.venv/bin/python scripts/verify-account-source.py devbox`. This one-time tool starts and closes a temporary local App Server for comparison and saves only a private SHA-256 fingerprint. Rust periodically checks the remote fingerprint; a mismatch disables account updates while task collection continues. Reverify after changing the local login or subscription type. When SSH is unavailable or disabled, quota/Token values age out from cache; no local replacement server is automatically launched. The current fingerprint has been verified.

Before BLE, Rust + SSH totaled 31.73 MiB RSS; the reconnect sample peaked at 32.92 MiB. See the [migration report](reports/rust-migration-result.md) for methodology and remaining verification.

## Workspace

- `firmwares/codex/`: upstream reference checkout on `feature/codex-companion`.
- `rust-bridge/`: resident service, Rust + system SQLite + a small CoreText C interface.
- `scripts/companion.py`, `scripts/passport/`: Python reference and rollback implementation.
- `config/bridge.json`: explicit SSH aliases; `--remote ALIAS` overrides it, `--local-only` disables SSH.
- `reports/companion-state.sqlite3`: private durable state; dry-run uses temporary state by default.
- `scripts/device.py`: list devices, read chip identity, monitor serial console.
- `tests/`: host bridge behavior tests.
- `backups/`: private original 8 MB Flash dump and SHA-256; excluded from Git.
- `.toolchains/`: workspace-local ESP-IDF 5.5.3 and compiler.
- `reports/`: build logs and connection notes.

## Build and validate

```bash
cargo test --manifest-path rust-bridge/Cargo.toml
cargo build --release --manifest-path rust-bridge/Cargo.toml
source scripts/env.sh
.venv/bin/python scripts/firmware.py build codex
.venv/bin/python -m unittest discover -s tests -v
```

To preview or install on this backed-up device, run `.venv/bin/python scripts/install-companion.py` or add `--install`. Stop the bridge before flashing. The installer checks the device serial and backup hash and verifies bootloader/table/identity before and after writing only the app.

The verified merged image is `firmwares/codex/build/FoloToy-AI-Passport-full.bin`. The firmware uses the official BSP, 240×320 LVGL screen, three keys, ES8311 audio and optional battery sensor. Frames are bounded and validated; sound runs outside UI/button tasks; stale/disconnected states are explicit.

## Original device and recovery

The original firmware is `trae_card 1.0.2`, ESP-IDF 5.5.3, ESP32-C3 revision 1.1, 8 MB Flash. Its partition table includes image/audio resources and device identity at `0x356000`, but no Recovery partition. The backup has no ESP image magic at `0x700000`; do not assume the current template's five-second UP-key recovery is installed on this device.

For this device, installation is app-only at `0x10000` with a maximum `0x300000` bytes, preserving its existing bootloader, partition table, identity and resources. Do not erase Flash. Keep the private backup locally: it includes device-specific identity data. `scripts/restore-original.py` restores only the original application partition after explicit invocation. Restoring has not been hardware-tested until actually performed.

[Official device guide](https://ai-passport.folotoy.cn/guides/create-your-own-play/) · [Codex app-server API](https://learn.chatgpt.com/docs/app-server)

The hardware USB handover regression is `.venv/bin/python scripts/test-usb-handover.py` (stop the bridge and dismiss unread alerts first; keep USB attached and BLE paired). It uses a temporary database, establishes BLE, exposes the serial path, and verifies USB takeover explicitly disconnects BLE and keeps it disconnected. It does not create test alerts. Restart normal monitoring afterwards.

The header divider is removed. Plain reset-card text sits above the reset time, both right-aligned with gray titles and dark 16 px bold values, without a card background or decoration. The read-only count comes from `account/rateLimits/read.rateLimitResetCredits.availableCount` using the existing 60-second polling cycle; it is independent of paid credit balance. Missing or stale data shows `--`, a confirmed empty balance shows `0`, and no redemption action is added. CDXM carries the count as an optional trailing field; legacy metadata defaults to unknown.

The home screen shows quota as a static 270-degree open ring with its percentage centered and reset countdown alongside, followed by seven horizontal daily-usage rows with no weekly summary. Each row shows an MM/DD date, a proportional bar, and a right-aligned compact token value. Dates, numbers and unit suffixes use the same 13 px antialiased font, at 18 px row spacing. Rows run newest first. All bars use the same orange; dates have no special highlight. Missing buckets show `--` without a bar; reported zero shows `0`. The seven calendar days end on the latest reported date up to the Mac calendar date. Stale data and date rollovers clear old data until refreshed. Polling remains five minutes. CDXM carries normalized values, compact daily amounts and MM/DD labels; legacy day-only labels remain accepted. One draw object renders rows directly without an additional framebuffer or animation task.

Reset countdowns below 24 hours retain minute precision, for example `3h 07m` or `59m`.
[Reset cards and connection navigation](docs/usage.md#reset-cards-and-connection-pages)

[Firmware workspaces: create, build and install](docs/firmware-workspaces.md)
