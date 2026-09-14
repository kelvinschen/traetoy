[简体中文](VALIDATION.zh_CN.md)

# Validation — 2026-09-09, version 0.6.1

Build: PASS — official `build codex-pet`; application 2,181,488 bytes, merged image 2,247,024 bytes. Protected app-only installation passed before/after verification. No shared board or audio changes.

Host tests: PASS — four brightness levels, exact 60/3600-second boundaries, message priority, running/dismissal/key transitions and duplicate-event inactivity; complete Pet gate also passed (4,287 frames and selected sound source hashes).

Device tests: PASS — `tools/device_test.py --power`, report `reports/pet-v61-device.json`: commanded/applied backlight levels 85/50/35/0, clock-aged 59/60 and 3599/3600-second boundaries, running wake, wake-only first key, all three notification kinds overriding running, dismissal to 50%, duplicate messages without renewed alerts. Desktop service restarted afterward.

Unverified: one uninterrupted physical hour and instrument-measured luminance/PWM. Device diagnostics confirm the display worker called the existing BSP backlight API; they are not a photometer reading. Prior audio/waiting limitations below still apply.

# Validation — 2026-09-09, version 0.6.0

## Build

PASS: `.venv/bin/python scripts/firmware.py build codex-pet` and `build codex`. Pet application: 2,181,200 / 3,145,728 bytes; merged image: 2,246,736 bytes. The default Codex consumer still accepts only kinds 1–2; Pet explicitly enables waiting kind 3. Rust release build and Clippy with `-D warnings` pass.

Pet merged SHA-256: `86431e5526eb92f21e7626eb78cecc721a0410b488aee5960553bf50c9cae5fc`. Protected app-only installation verified the original bootloader, partition table and card identity before and after writing. Board sources, audio clocks and channel configuration are unchanged.

## Host tests

PASS: 29 Rust tests, including waiting flag recognition, one reminder per waiting episode, resolution cancellation, completion coexistence, delayed pre-connection snapshot rejection, reconnect baselines and old-firmware capability fallback.

PASS: Pet host gate. All 4,287 C animation frames match Python zlib (CRC `01db9af3`); 21 sequence boundaries and existing rendering, behavior, power and notification-expiry checks pass. All 84,902 audio samples match the source WAV hashes and generated PCM. The three clips contain 35,945 / 36,000 / 12,957 samples (success / failure / waiting), with bounded peaks and silent endpoints. PCM occupies 169,804 flash bytes and streams through a 512-byte stack buffer. No realtime synthesis or full-clip RAM allocation is used.

## Device tests

PASS: `tools/device_test.py --audio-timing --expiry --perf --seconds 6 --output reports/pet-v60-device.json`.

- Output-worker times: success 2.196 s, failure 2.199 s, waiting 0.761 s. Source durations are 2.247 / 2.250 / 0.810 s; DMA drains the remaining tail after worker completion. This is not an acoustic duration measurement.
- Waiting kind 3 is accepted, displays `WAITING`, and duplicates neither replay sound nor add unread snapshots. Renderer screenshot `reports/pet-v60-waiting.png` was visually inspected.
- The 15-second expiry, information-page pause, duplicate timer suppression, older snapshot restoration and OK dismissal pass.
- All six sequence performance windows report 59.3–59.7 software FPS. After tests there are zero unread messages; production USB synchronization is restored on compatible firmware 0.6.0, with local and devbox sources healthy.

Evidence (ignored): `reports/pet-v60-device.json`, `reports/pet-v60-service.json`, and the waiting screenshot. Source WAVs and provenance are retained under `assets/sounds/`.

## Limitations and unverified checks

Local waiting detection is **unavailable**, not passed: this Mac's desktop App Server uses stdio and exposes no reusable control socket. Local completion/stop detection still works. Remote approval/input detection is implemented using explicit App Server flags and covered by host fixtures; a real user approval/input interaction was not induced during this run. Device kind-3 playback was tested through the actual USB protocol.

Acoustic pitch/timbre and speaker SPL, BLE, optical scan smoothness, physical keys/backlight, real uninterrupted one-hour idle soak and endurance were not measured in this run. The earlier rapid BLE partial-frame reconnect stress failure remains unresolved. Historical power/footer checks are recorded in earlier change entries; they were not all rerun here. Device notifications remain RAM-only.
