[简体中文](hooks.zh_CN.md) · [Home](../README.md)

# Codex hooks

Local and SSH hosts use the same live event transport. Each host stores definitions in `~/.codex/hooks.json`, calling one native sender at `~/.codex/passport/hook`. `hook.py` is the resident receiver. Installation requires a C compiler (`cc`) on each host and compiles for that host’s architecture; the receiver requires Python 3. The bridge launches its local receiver from the workspace and a remote receiver over SSH; no remote daemon installation is needed.

## Install

```bash
python3 scripts/codex-hooks.py install --remote HOST_ALIAS --trust
python3 scripts/codex-hooks.py status --remote HOST_ALIAS
cargo build --release --manifest-path rust-bridge/Cargo.toml
./scripts/bridge-service.sh restart
```

Replace HOST_ALIAS with an alias already configured in `config/bridge.json`; repeat `--remote` for more hosts. The installer merges only Passport handlers and backs up existing hooks before changes. `--trust` uses Codex's normal `hooks/list` and `config/batchWrite` review workflow for those seven definitions, backing up `config.toml` first. Codex stores its trust hashes under `hooks.state`; script definitions remain in hooks.json. Existing notify commands and other hooks remain intact. Without `--trust`, review and enable the installed commands through Codex `/hooks` before use. **Installation does not activate hooks in already loaded Codex sessions.** The installer refreshes existing remote sessions through their App Server; `activation.state=reloaded` confirms success. Refresh uses wsproto in this workspace’s `.venv`; when unavailable, it explicitly returns `restart_required`. This local desktop Codex has no attachable refresh endpoint, so the installer requires quitting and reopening Codex. Restarting Passport alone does not refresh Codex sessions.

```bash
python3 scripts/codex-hooks.py uninstall --remote HOST_ALIAS
```

Uninstall removes only Passport handlers. It refreshes remote sessions to apply removal; restart local Codex, or existing sessions may continue running cached hooks. The helper and private backups remain available for rollback. Remove the alias from bridge configuration if its receiver should also stop. Status reports installation, not runtime health; use `bridge-service.sh status` for source/device health. Source healthy means the receiver is online, not that existing Codex sessions loaded hooks; validate first-time installation with actual task start and completion events.

## Events and lifecycle

| Hook | Meaning |
| --- | --- |
| UserPromptSubmit | Start/update this live turn; close previous input waiting |
| PermissionRequest | Notify an approval wait |
| PreToolUse | Notify only request_user_input / request_user_input_async |
| PostToolUse | Resolve synchronous waits; async input stays open |
| Stop | Observe the active transcript, without declaring completion |
| Interrupt | End the turn as interrupted |
| SessionEnd | Close remaining live state |

Codex 0.153.4 can continue after Stop, and failures can omit Stop. Therefore the receiver watches only transcripts supplied by new hook events, starting from their captured byte offsets. macOS kqueue / Linux inotify trigger appended reads. `task_complete` determines success/failure; `turn_aborted` handles interruption. No session discovery, historical scan or reconnect catch-up occurs. This final-record format is version-dependent and must be retested when Codex changes. An abrupt Codex crash without a final record is not inferred as success; crash recovery is outside this design.

Ephemeral Codex work, such as automatic thread title generation, has no transcript. Its start/wait hooks are ignored so it cannot leave a phantom running task. A transcript must be opened and watched successfully before a task enters the running count.


Hooks return neutral `{}` and pass input through a private Unix stream socket with a 50 ms IPC deadline. The native sender starts no Python process. The existing receiver parses input in memory, never writes it to disk, and sends only metadata over SSH. It registers transcript observation before acknowledging input so very short turns cannot finish before observation begins. Ordinary PostToolUse without a matching wait is dropped before title lookup, approval hashing or Rust event delivery. Titles are looked up only on lower-frequency start, stop and waiting events. Approval correlation retains a tool/input digest. Root tasks are tracked; child-agent hooks are ignored. Receiver pulses every five seconds distinguish idle from failure. Account quota/token RPC is independent.

Disconnected events are dropped. Restarting a receiver starts empty, and reconnecting a device does not restore old notifications. In-memory tracking supplies running/waiting state. The existing bridge database supports current online delivery transactions and counters, but is not an offline event queue. Device notifications already received remain under firmware control; OK never approves a Codex request.

## Validation

```bash
python3 scripts/codex-hooks/test_hooks.py
python3 scripts/codex-hooks/test_codex_runtime.py
python3 scripts/codex-hooks/benchmark.py --count 60 --title-hit --max-cpu-ms 15
cargo test --manifest-path rust-bridge/Cargo.toml
cargo clippy --manifest-path rust-bridge/Cargo.toml -- -D warnings
```

The runtime suite launches the installed Codex against a loopback mock provider in a disposable CODEX_HOME. It exercises ephemeral title work, success, failure, Stop continuation, synchronous/asynchronous input, approval, interruption, and installation/removal reloads in already loaded sessions without real model/account requests. On Linux set CODEX_BIN to the installed executable. These are host tests, not device tests. Live hardware requires checking source state and receipt of notifications on the connected device separately.

To deliberately send the runtime fixtures through a running local receiver to real hardware, set `PASSPORT_TEST_LIVE_SOCKET` to its absolute `events.sock` path. This emits real notifications and sounds. Use the same option on the SSH host for remote hardware-path checks.

The performance benchmark uses an isolated receiver and synthetic tool input. It includes actual shell/native sender startup and extrapolates single-core CPU usage at one callback per second. It sends no device notifications.

## Quota snapshots

Quota is read at startup and every five minutes; task events never postpone calibration. The receiver extracts only fresh token_count.rate_limits windows from new records in already watched transcripts, without history scans or new model/account requests. Only the configured account_host, while its account identity check is valid, may update the codex bucket. Other hosts, buckets, malformed snapshots and older timestamps are ignored. Local account/read RPC verifies identity every minute; this is not a cloud quota fetch.

Task snapshots preserve reset-credit and token-activity fields. Reset credits expire after 15 minutes without a successful calibration, even while snapshots arrive. Quota stays fresh for 10 minutes; failed queries retain the last known values and update time without making hook transport unhealthy. There is no offline replay. Hosts without quota events still use five-minute calibration.

The bridge accepts up to five seconds of forward clock skew from the source and clamps the accepted timestamp to its own receive time. Larger clock errors are rejected. This prevents small Mac/Linux clock differences from silently dropping live snapshots or creating future freshness timestamps.
