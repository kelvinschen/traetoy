[简体中文](README.zh_CN.md)

# Codex Pet

A 240×320 Codex companion with a centered Bloub cloud, plain remaining-quota percentages, and an expanding result area. Mac/Rust/BSP, collectors, USB/BLE identity and pairing remain shared; the bridge also routes attention notifications and adjusts token rounding at unit boundaries.

Selected notification audio: **success L** (Puzzle Solved, 2.247 s), **waiting N** (Sheikah Sensor Ping, 0.810 s), and **stopped/failed V1** (Game Over, +7 semitones, original playback speed, tail cut at 2.25 s). The failure clip is shortened by removing its tail, not by speeding up the melody. The selected source WAVs and provenance are retained in `assets/sounds/`. All clips are 16 kHz mono, peak-limited to the existing 3000/32767 ceiling, with 5 ms endpoint fades; codec volume is 65%. Speaker loudness/timbre has not been measured. The two-second cooldown remains. `tools/bake_sound.py` stores variable-length PCM in flash; playback uses one 512-byte buffer and performs no realtime synthesis. The host gate checks every generated sample and source hash.

`waiting-alert-v1` adds kind 3 and WAITING. Local and remote live hooks detect approvals and input requests once per waiting episode. OK dismisses only the device notification. See [hook setup](../../docs/hooks.md).

## Use

- **Home:** the cloud is centered at y=154. Results move it to y=99 over 380 ms. The latest Chinese title appears below; workspace and elapsed duration share one row. `DONE` is orange; multiple results show `DONE (2 UNREAD)`. Stopped/failed turns use `STOPPED`. There is no fixed top-right unread dot; the original animation dot remains.
- **Message stack:** newest first, up to eight immutable snapshots. Each newly exposed result gets 15 seconds on home, then automatically leaves the stack. Information pages and the gallery pause the timer. New arrivals on those pages join the stack without changing pages. Duplicates cannot reset the timer, replay sound, or restore dismissed results. Overflow evicts the oldest; reboot clears the stack.
- **UP/DOWN:** cycle Home → Quota/reset → 7-day tokens → Connection/system in either direction. Information pages remain open until a key changes them.
- **OK:** on home, acknowledge one result and wink; remaining results stay expanded. On an information page, return home without acknowledging anything. With no unread result, OK gives a friendly wink.
- **Hold OK:** return home without acknowledging. **Hold UP:** open the six-sequence diagnostic gallery; UP/DOWN browse and OK exits.

Home shows the longest available quota window at bottom-right, e.g. `94%  2d 04h`; the percentage uses dark 18 px Montserrat and the countdown uses gray 13 px, with aligned digit baselines. Absent/stale quota is hidden. Bottom-left shows a play icon and running task count; idle leaves the bottom-left area blank. A disconnected link or unhealthy source shows only an unplug icon, without a numeric placeholder. The footer updates independently of unread-message animation. The reset page shows its large remaining percentage and countdown, the other available window, reset-credit count and up to six expiry/status rows. Unknown credit details remain explicit. These are read-only views: nothing redeems a credit. Connection/system shows transport, last state age, source health, the measured battery level (or `--`), current brightness, firmware version, uptime and software FPS.

The token page uses the existing account `account/usage/read` path, refreshed by the bridge hourly. Seven calendar buckets end on the latest reported date, which may be yesterday. The page shows the cutoff; missing days stay `--`, known zero stays zero, and the total is unavailable if any day is missing. Stale/disconnected data is hidden. Counts below one billion use M; B always has one decimal (`1.0B`, `1.2B`). Daily labels separate number and unit vertically. The existing four-character wire values remain rounded; very large labels that cannot fit a column use an ellipsis. The bridge no longer rounds 999.xM up to B before the count reaches one billion.

The screen uses soft gray-white (`#ECECEC`), a dark cloud and antialiased Montserrat at 11/13/18/34/60 px. Chinese content reuses bridge-rendered bitmaps; long workspace names are cropped with an ellipsis before the duration. Compact status labels remain English. A result means the current response turn ended, not that the whole project or its tests succeeded. Two-second audio coalescing is retained, and the visible result keeps its corresponding animation even while other tasks run; after the last result leaves, work/idle/offline resumes.

## Automatic screen off

Brightness has four levels: unread/new messages use 85%; running tasks without messages use 50%. With neither, the first idle minute uses 85%, then 35% until one hour, then the backlight turns off and rendering pauses. Running tasks, unread messages, new arrivals and keys reset inactivity; heartbeats, metadata and duplicates do not. Messages take priority over running tasks. A first key while dark only wakes, preserving the page and unread state. Wake draws a complete frame before restoring the appropriate brightness. USB/BLE remain active, and the last known positive running count conservatively retains 50% after a disconnect. This is display sleep, not MCU deep sleep.

## Selected sequences

All six use the cloud shape and the unchanged upstream engine:

| State | Sequence (seconds) | End behavior |
| --- | --- | --- |
| Idle | blase 5 → swirl 4 → play 4 → somnolent 5 | Loop |
| Working | attentif 6 → thinking 3 → wide 6 → thinking 3 → curieux 6 | Loop |
| Completed | notify 2.2 | Living notify tail until the result leaves the message stack |
| Acknowledged | wink 3 → excite 3 | Return to the current live state |
| Stopped/failed | surpris 2.5 → alert 3 | Living final-pose tail until the result leaves the message stack |
| Offline/source error | effraye 2.4 → exclaim 4 | Loop |

Working ends in a curious expression; winking belongs to acknowledgement. Notify pops once, then loops a four-second living tail; it has no 20-second timeout. OK plays the full six-second acknowledgement before returning to the next unread result or live state. New results still enter the stack during acknowledgement, and repeated OK can dismiss results without restarting the animation. Older completed results retain notify without replaying the arrival pop. Link/source warnings remain visible while the result owns the avatar.

Looped sequences append a 450 ms direct return morph to their first expression. A 150 ms baked seam blend closes the remaining blink/breath/gaze phase difference. Completion and stop include four-second living tails; the final `alert` pose is the upstream tilted exclamation mark. Internal transitions do not detour through neutral. Action-to-action changes go directly through the upstream setter; an intermediate idle previously discarded the outgoing eye offset at wide → thinking. Arbitrary event interrupts use a 140 ms runtime pixel crossfade. Expressions are acting within coarse real states, not claims about individual tool phases. A disconnected source never becomes success.

## Build and install

Created from the blank template with `scripts/firmware.py new codex-pet`. Read the root [workspace guide](../../docs/firmware-workspaces.md).

```bash
cargo test --manifest-path rust-bridge/Cargo.toml
cargo build --release --manifest-path rust-bridge/Cargo.toml
npm ci --prefix firmwares/codex-pet/tools
node firmwares/codex-pet/tools/bake.mjs
node firmwares/codex-pet/tools/bake_icons.mjs
.venv/bin/python firmwares/codex-pet/tools/bake_font.py
.venv/bin/python firmwares/codex-pet/tools/test.py
.venv/bin/python scripts/firmware.py build codex-pet
scripts/bridge-service.sh stop
.venv/bin/python scripts/install-companion.py --workspace codex-pet
.venv/bin/python scripts/install-companion.py --workspace codex-pet --install
scripts/bridge-service.sh start
```

Use only the protected app-only installer on the backed-up board. Never erase flash or directly flash a merged image. Creating/building a workspace does not switch the live device or service. The current board retains its original bootloader/table; the template Recovery is not installed.

## Implementation and validation

- `tools/sequences.mjs` defines product sequences; `tools/bake.mjs` samples the pinned original engine at 60 Hz into 192×192 four-bit frames. Six sequences contain 4,287 frames and 1,087,742 bytes of deduplicated DEFLATE/XOR payload.
- `main/pet_behavior.c` selects sequences and looping tails from real events. `main/pet_ui.c` owns the pure renderer and fixed-point reversible smoothstep movement. Position changes need no additional image assets.
- `main/main.c` owns direct SPI rendering, two DMA stripe buffers, and absolute-time playback. Protocol collection and audio run outside the display task. The shared 40 MHz SPI, 60 Hz panel timing remain unchanged; backlight follows the four-level activity policy; LVGL is not started.
- `tools/bake_font.py` generates 4-bit outline coverage from the existing OFL Montserrat source in `../codex/assets/fonts/`; the font payload is 101,255 bytes plus 475 glyph records.
- `main/pet_codec.c` checks compressed bounds, seeks from keyframes and catches up skipped frames. The vendored miniz symbol is renamed and link-checked to avoid the ESP32-C3 ROM ABI conflict.
- Protocol, title and alert storage compile from `../codex/main/companion_*.c`. Changes to shared contracts require validating both consumers.

The host gate checks all decoded frames against Python zlib, exact loop-seam endpoints, random seeks, dirty stripe coverage, tiled/full rendering at different positions and crossfades, reversible layout motion, event selection, duplicate alerts and immutable snapshots. Generated source previews are in ignored `build/previews/`.

With the service stopped, USB diagnostics support `PET|STATS|END`, `PET|CLIP|0|END` (0–5; -1 exits), `PET|KEY|2|END` (UP=0, DOWN=1, OK=2, BACK=3, GALLERY=4), and `PET|SHOT|END`. `PET|IDLE|0..3600|END` ages only the inactivity clock for USB testing; it never changes the production one-hour threshold. `--power` checks the boundary and wake/acknowledgement rules with that clock injection.

```bash
.venv/bin/python firmwares/codex-pet/tools/device_test.py --verify --perf --seconds 12 --shot reports/pet-home.png
```

This sends synthetic Chinese tasks/results and sounds, acknowledges its test results, then measures all six sequences. Screenshots are software renderer output, not LCD readback; capture pauses animation and is excluded from performance windows. A 60 Hz software target does not prove physical tear-free scans. Restart the shared service after testing.

See [sources/licenses](THIRD_PARTY.md), [changes](CHANGELOG.md), and [validation results](VALIDATION.md). Report Build, Host tests, Device tests and Unverified separately.
