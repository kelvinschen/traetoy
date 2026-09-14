[简体中文](usage.zh_CN.md) · [Home](../README.md)

# User guide

## Connect and manage

Open `macos-app/build/Passport.app`. Passport appears only in the menu bar and starts the Rust backend. A usable USB data connection takes priority; otherwise paired BLE reconnects automatically. Keep the Mac awake and the device powered on; Wi-Fi is unnecessary.

The menu separates service state, USB/BLE connection, firmware compatibility and local/SSH source health. An unknown or old firmware receives no Codex business data. The current firmware supports the Passport identity query.

| Menu action | Effect |
| --- | --- |
| Start service | Start collection and automatic connection |
| Stop service | Stop collection, release the device and close owned SSH children; keep the menu app |
| Restart service | Wait for the old instance to exit, then start |
| Reconnect device | Rebuild only the device connection; preserve pending delivery |
| Start at login | Independently register the menu app as a login item |
| Quit Passport | Stop the backend before closing the menu app |

Stopping does not change login startup. Opening the app again starts the service. Closing a terminal has no effect. A menu-app crash stops its backend after a ten-second ownership grace period. Repeated backend crashes stop automatic recovery after three retries per minute. A stop that exceeds 40 seconds displays an error and offers explicit forced termination.

```bash
cd /path/to/traetoy
./scripts/bridge-service.sh start
./scripts/bridge-service.sh status
./scripts/bridge-service.sh stop
./scripts/bridge-service.sh restart
./scripts/bridge-service.sh reconnect
./scripts/bridge-service.sh quit
```

CLI actions use the same app controller. `status` returns structured app/backend/device/source state. Launchd runs Rust only while requested by Passport; its plist remains `~/Library/LaunchAgents/cn.folotoy.codex-passport.bridge.plist`. No sudo is required. If macOS requires login-item approval, use System Settings → General → Login Items.

## Screen and controls

- The gauge shows remaining quota. `Resets in` retains minutes below 24 hours.
- `Reset cards` is a read-only available count; the device does not redeem cards.
- Seven daily rows show MM/DD dates newest first, uniform orange bars and token amounts. K/M/B mean thousand/million/billion. There is no weekly summary row.
- The window ends on the latest reported date and can exclude today. Missing is `--`; confirmed zero is `0`. Token activity is neither subscription quota remaining nor a bill.
- The bottom shows running task count. Task pages show titles, projects/workspaces, and current-turn duration without seconds.

| Action | Result |
| --- | --- |
| Short OK on home | Open unread alerts first, otherwise running tasks |
| Any function key while screen is off | Wake without navigation; new alerts also wake automatically |
| UP/DOWN on tasks | Select tasks/change pages |
| Hold OK | Return home without acknowledging an alert |
| Short OK on alert | Acknowledge it and display the next |

Alerts are newest first, with at most eight stored; overflow drops the oldest. Each auto-acknowledges after 30 seconds of accumulated visible time. A newer alert or returning home pauses that timer. Clearing the stack restores the previous page. Device restart clears unread alerts in RAM. Completion refers to a response turn, not the lifetime of a multi-turn conversation.

After 60 seconds without input or a new alert, backlight duty drops from 75% to 35% while monitoring continues. Input or a new alert restores 75%. Duty percentage is not a linear measure of perceived brightness.

One hour without a new notification turns the screen off. Ordinary refreshes and awake navigation do not extend the timer. New alerts wake with sound; manual wake starts a fresh hour. Monitoring continues while alert visible-time accounting and redraws pause.

## Refresh and sources

| Information | Interval/source |
| --- | --- |
| Device state and duration | About 3 seconds |
| Local/remote tasks | Live hooks; receiver health every 5 seconds |
| Quota and reset cards | At startup and every 5 minutes, one shared request; task snapshots update quota between requests |
| Token activity | Hourly; upstream reporting can lag |
| Battery | About 30 seconds |

Local and SSH remote task events use independent hooks; see [setup](hooks.md). account_host independently selects account data. Cloud tasks are not covered. Disconnection never replays old events, and account errors do not affect task health.

## Troubleshoot

```bash
./scripts/bridge-service.sh status
tail -n 30 reports/bridge.log
```

- Stopped: run `start`; do not launch a second Rust instance alongside it.
- No screen updates: wake the device and check the USB data cable or Bluetooth, then try `restart`. A fresh `CDX_ACK` means received, not read by the user.
- BLE timeout: check power, proximity, Mac Bluetooth and the corresponding application's permission in System Settings → Privacy & Security → Bluetooth. Reboot alone does not require pairing again.
- Remote unavailable: check `ssh HOST_ALIAS` in a terminal (substitute your configured alias). Fix authentication/network access; monitoring retries. Never put SSH private keys in the LaunchAgent.
- `--` values: investigate missing upstream data, SSH failure, stale data or identity verification; this does not mean zero quota. Reverify after account changes using the developer guide.
- Workspace moved: quit Passport, rebuild the app and run `./scripts/bridge-service.sh install` from the new location; re-enable the login item if necessary.

Logs rotate at 2 MB with three backups and can contain task titles/paths; sanitize before sharing. See the [developer guide](development.md) for pairing, builds, firmware installation and resource measurement.

## Reset cards and connection pages

UP/DOWN on a root page cycles Overview → Reset cards → Connection. OK on Overview still opens unread alerts first, otherwise running tasks. Hold OK anywhere to return to Overview.

Reset cards shows the available count and nearest expiry. OK enters the list; UP/DOWN selects a card and OK opens details. UP/DOWN scrolls details; short OK returns to the list. Details include title, status, grant/expiry dates, timezone, type and description; redemption is not supported. Dates use the Mac's local timezone. `--` means unavailable, not an unlimited lifetime.

Connection separates the active USB/BLE transport, device data arrival, local/remote source health and account sync age. Source failure never becomes task completion. When the device disconnects, source status is marked cached. Alerts interrupt these pages and return to the previous page after acknowledgement.

At most six cards and four sources are displayed. Cards are expiry-sorted; capped results show loaded/available counts. Some responses provide only a count, in which case details are unavailable. Long names or descriptions end in ellipses. The pages reuse existing requests without increasing collection frequency.

[Firmware workspaces: create, build and install](firmware-workspaces.md)
