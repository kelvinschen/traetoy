[简体中文](CHANGELOG.zh_CN.md)

# Changes

## 2026-09-10 — Clearer notification audio

Increase codec output volume from 45% to 65% (approximately +10 dB on the driver volume curve). Preserve source WAVs and baked PCM sample-for-sample, timing, pitch and fades.

## 2026-09-10 — Lower notification volume

Reduce codec output volume from 85% to 45%.

## 2026-09-09 — 0.6.1 four-level backlight

Brightness has four levels: unread/new messages use 85%; running tasks without messages use 50%. With neither, the first idle minute uses 85%, then 35% until one hour, then the backlight turns off and rendering pauses. Running tasks, unread messages, new arrivals and keys reset inactivity; heartbeats, metadata and duplicates do not. Messages take priority over running tasks. A first key while dark only wakes, preserving the page and unread state. Wake draws a complete frame before restoring the appropriate brightness. USB/BLE remain active, and the last known positive running count conservatively retains 50% after a disconnect. This is display sleep, not MCU deep sleep. Notification sounds are unchanged.

## 2026-09-09 — 0.6.0 selected Zelda notification sounds

Use L for completion, N for actual waiting-for-approval/input events, and the selected V1 original-speed, tail-trimmed Game Over for stopped/failed turns. Bake all three 16 kHz PCM clips with independent lengths; retain gain, cooldown and bounded streaming. Add capability-gated waiting notifications, edge deduplication, pending cancellation and reconnect baselines. The current Mac exposes no App Server control socket, so local waiting detection is explicitly unavailable; remote detection uses the existing connection.

## 2026-09-09 — 0.5.4 continuous audio playback

Fix the six-syllable voice stretching on ESP32-C3: realtime floating-point synthesis took 4.253 seconds to feed a 0.61-second phrase. Bake identical PCM into flash and stream bounded buffers. Device output-worker timings are now 0.566/0.564/0.563 seconds; DMA drains the tail afterward. Keep timbre, gain and notification timing unchanged.

## 2026-09-09 — 0.5.3 varied bot voice

Replace the three-note phrase with six short syllables, varied rhythm, alternating pitch scoops and round/bright timbre changes. Keep the moderate gain ceiling, smooth fades, 15-second notification expiry and sound cooldown.

## 2026-09-09 — 0.5.2 15-second notifications

Reduce each newly exposed home notification from 30 to 15 seconds. Preserve information-page/gallery timer pause, newest-first order, duplicate suppression and manual acknowledgement. Add soft rising/falling three-note bot sounds (0.51 seconds), smooth envelopes and moderate waveform gain 1800 → 3000; keep codec volume 85% and sound deduplication.

## 2026-09-08 — 0.5.1 blank idle footer

Remove the coffee icon during idle. Keep the running icon/count and disconnected/source-error icon. Animation, quota typography and one-hour display sleep are unchanged.

## 2026-09-08 — 0.5.0 selected animation and idle screen off

Apply all six selected sequences, ending work with curieux for six seconds. Keep the 0.4.2 layout and footer. Acknowledgement owns its full six seconds even when new results arrive. Turn off the backlight and pause rendering after one hour without running tasks, new results or keys; wake on results, running tasks or a wake-only first key. Heartbeats and duplicate results do not keep the screen awake. Collection and pairing remain active.

## 2026-09-08 — 0.4.2 quota emphasis

Emphasize the home remaining percentage with dark 18 px text next to the gray 13 px countdown. Align digit baselines and bound long countdowns so they cannot collide with the running count.

## 2026-09-08 — 0.4.1 home footer

Add a running icon with the live task count. Idle and offline/source-error states show icons only. Use one gray 13 px style for the home percentage and reset countdown, and refresh the footer when connectivity changes.

## 2026-09-08 — 0.4.0 slower sequences and persistent notify

Apply the selected longer idle, work, stop and offline timings. Keep notify's orange marker and living tail until the result leaves the message stack, including while other work runs; confirmation and expiry restore the next result or live state. Reuse a short tail instead of baking a 20-second notification. Remove the redundant intermediate idle that caused the wide-to-thinking eye-position jump; leave the upstream engine unchanged.

## 2026-09-08 — 0.3.0 information pages and timed message stack

Implement four-page UP/DOWN navigation, paused 30-second LIFO message expiry, orange DONE/unread headings, one-row workspace/duration and a single compact home quota. Add reset-credit expiry/status, real daily token charts with fixed one-decimal B labels, and connection/system/battery data. Preserve animation movement, audio deduplication and protected installation. Expand the antialiased outline font sizes; keep M below the raw billion threshold in the shared bridge.

## 2026-09-08 — selected cloud sequences and result layout

Replace the 36-clip gallery/live selection with six user-selected continuous cloud sequences, direct internal transitions and living hold tails. Center the cloud in normal use, animate it upward over 380 ms for unread results, and show the latest immutable Chinese result snapshot on home. OK acknowledges one result directly. Keep both remaining-quota percentages anchored at the bottom and the independent unread dot at the screen's top-right. Use a soft gray-white background, a dark avatar, antialiased Montserrat labels, and 70% backlight after device feedback. Retain the original animation dot. Shared desktop, transport, identity and recovery paths are unchanged.
