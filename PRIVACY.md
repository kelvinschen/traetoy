[简体中文](PRIVACY.zh_CN.md)

# Privacy and local data

Traetoy is local companion software for a Mac and a compatible AI Passport
device. It is not a hosted service and does not provide a project-operated
telemetry endpoint.

## Data handled locally

- task titles, workspace or project labels, task timing, and notification state;
- Codex account quota and token-activity summaries obtained from the configured
  local or remote account source;
- configured SSH aliases and local service state;
- a BLE pairing key stored in local configuration with restrictive permissions
  and in device NVS; and
- a local SQLite delivery-state database and local diagnostic logs.

Task prompts, tool arguments, answers, account credentials, and conversation
contents are not intentionally sent to the device. The device receives rendered
task-title bitmaps and compact status metadata needed for its display.

## Local and remote transport

The Mac connects to the device over USB or authenticated BLE. Optional remote
hosts send event metadata over SSH to the Mac. Account data uses the configured
Codex/App Server connection. These transports are controlled by the user's
machine, account, SSH configuration, and network; they are not Traetoy-operated
servers.

## Storage and deletion

Local configuration, logs, reports, pairing material, and device backups are
ignored by Git and must never be committed. Stop the bridge before deleting its
local state or pairing data. Removing a pairing key requires reprovisioning
before BLE can reconnect. The project does not guarantee recovery of user data
that has been manually deleted.

## User responsibilities

Review configured SSH hosts before enabling remote monitoring. Do not attach
shared devices to sensitive workspaces unless task-title display and the local
storage described above are acceptable for that environment.
