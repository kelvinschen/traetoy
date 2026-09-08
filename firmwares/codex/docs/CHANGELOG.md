<p align="right">
  <a href="CHANGELOG.zh_CN.md">简体中文</a> · <strong>English</strong>
</p>

# Changelog

## Unreleased

- Add a transport-neutral Passport firmware identity/capability query for the native menu-bar manager; preserve Codex display, alert and power behavior.

- Give completion workspaces a dedicated 170 px row at 16 px; place the host and duration underneath. Keep the 3200-byte bitmap and snapshot host metadata separately, avoiding early project truncation.

- Add root UP/DOWN navigation for reset cards and connection health. Cards show expiry-sorted details, issue/expiry dates, timezone and description without redemption. Reuse existing quota/source collection and send bounded auxiliary metadata only when it changes; notifications return to the interrupted page.

- Increase completion project/host text from 13 px to 16 px within two 84×16 bitmap regions, preserving the title font. Notification diagnostics now use production Rust bitmaps.

- Use a title-first completion layout with a small status check, a thin divider, an orange folder icon, stacked project/host labels and right-aligned duration. Repack metadata within the same alert tile and reuse existing pixel buffers.

- Automatically turn the screen off after one hour without a new alert; manual wake restarts that timer. Any function key wakes without navigating; a new completion alert wakes automatically. Pause alert visibility timers and screen redraws while off; keep transport and collection active.

- Restore idle backlight duty to 35% after real-screen feedback; active duty remains 75%.

- Lower idle backlight duty from 35% to 15% after 60 seconds without input or a new alert; input and new alerts still restore 75%.

- Remove the reset-card background and stacked-card decoration. Use matching right-aligned gray titles and dark 16 px bold values for reset cards and reset countdown.

- Place the reset-card panel above the right-aligned reset countdown, retaining space for an optional second quota window.

- Right-align reset countdown opposite the quota ring and move its reset-card panel 8 px closer; retain room for a second quota window when present.

- Remove the header divider, move reset countdown to the upper right, and show available reset cards below it. Read the count from existing account polling; unavailable or stale counts display `--`.

- Enlarge the quota ring from 86 to 100 px diameter with a 7 px stroke, using the space above daily usage while keeping the percentage centered.

- Replace the quota number and horizontal meter with a static 270-degree open ring, centered percentage and adjacent reset countdown. Preserve the seven usage rows and show an empty ring for stale quota.

- Use one consistent orange for all daily usage bars and remove the usage-dependent color scale.

- Order daily usage newest first and shade bars from pale orange through orange to deep orange-red according to their relative usage in the displayed seven-day window. Remove latest-day highlighting.

- Replace vertical daily columns with seven horizontal rows: MM/DD date, proportional bar, and right-aligned usage. Remove the weekly summary and use a uniform font for numbers and units.

- Use a consistent 12 px size for all daily token numbers and 9 px units, with baseline alignment and 34 px columns to preserve spacing.

- Enlarge daily token numbers to 13 px (12 px for wide values) and draw unit suffixes separately at 8 px on a shared baseline, preserving natural spacing and the seven-column layout.

- Use three-letter weekday labels (Mon through Sun) below the seven daily bars instead of calendar dates.

- Restore natural letter spacing for daily token values and give each of the seven columns 33 pixels to improve readability.

- Replace the token line chart with seven daily bars, compact values above each bar, and day-of-month labels. Highlight the latest day and group `7d` with its total. Preserve missing/zero values and extend metadata with daily labels.

- Remove the TOKENS heading, widen the two usage summaries, and label the chart zero baseline and a rounded-up upper bound. Keep reset countdowns below 24 hours in hour/minute or minute format.

- Group quota reset time beside its percentage; show Today and 7d in one line above a static seven-day daily-usage chart. Draw gaps for missing dates and extend metadata compatibly for normalized chart points.

- Keep one companion transport at a time: USB closes BLE and takes priority; connect BLE only without usable USB. Show only the active transport icon in the header.

- Preserve USB control lines when opening the companion serial port so USB takeover preserves device state. Refine the battery to 32 × 16 pixels with 13 px antialiased digits.
- Set the battery to 32 by 16 pixels with charge number inside (without a percent sign) and contrast-aware fill. Automatically confirm each alert after 30 seconds of accumulated visible time, resume interrupted alerts with their remaining time, and return after the stack is empty.

- Wake the companion loop on input or packets instead of polling at 100 ms; skip unchanged display values and sub-minute duration updates. Dim the backlight from 75 to 35 percent after one idle minute, restoring it on button press or a new alert, and sample battery charge every 30 seconds.

- Add an authenticated BLE transport with USB provisioning, bounded fragmented commands, replay protection and a transport-specific header icon. Preserve USB fallback. Compress title banks and share canvas storage to accommodate the BLE stack without PSRAM.

- Keep a newest-first stack of up to eight unread task alerts. Short OK confirms one, long OK returns home without clearing, home OK reopens pending alerts, and a header badge shows the unread count. Oldest alerts are evicted at capacity.

- Redesign completion alerts as a small left check and right-hand task details: up to three title lines, elapsed time and workspace; remove the alert quota summary and reuse existing image memory.

- Move USB connection status into a compact header icon, shrink the bottom task band and give token statistics more space.

- Identify running tasks by their workspace/project, including original Git projects for linked worktrees; show minute-level durations without prefixes and use a three-second USB refresh interval.

- Add dated account token activity (day and trailing seven days), per-turn task duration, four-level antialiased Chinese titles and larger detail text; set audio volume to 100 percent and remove redundant quota labels.

- Remove quota animations and fill the battery icon from the live fuel-gauge percentage, including an immediate initial reading.

- Use a continuous rounded quota bar with a 600 ms value transition and a subtle three-second endpoint glow; remove dense tick marks.

- Replace the companion UI with PAPER METER, the official Codex icon, Chinese task-title browsing, and long-OK return navigation; remove sound controls and key-hint footers.

- Hide unavailable Codex quota windows and move task status into the freed space.

- Add a USB Codex companion dashboard with quota freshness, completion alerts, mute/dismiss controls, and a validated serial protocol.
- Added the supplied 80-byte CW2017 profile for the specified 520 mAh cell, including content/update-flag checks, verified writes, the required restart sequence, and bounded SOC-readiness polling.

- Reorganized the documentation by function area with a dual entry point: the root `AGENTS.md` is now a thin router (hard constraints + task routing only) and the detailed AI workflow lives in `docs/development/ai-guide.md`; `agent-guide.md` was folded in. `docs/development/` gained a second level (`engineering/`, `ci/`, `release/`), and the `plays/` application archive and `experiences/` moved into a `docs/reference/` area with a dedicated README. Removed `docs/software-design/` (empty scaffold); folded the three `assets/{fonts,images,music}/README` leaves into the `assets/` README; flattened the six `project-completion` sub-documents into a single file; and unified each directory to a single README, eliminating every `INDEX` file and a duplicated experience index. All cross-references and bibliographic links were updated; no content was dropped.

- Made mini-program BLE install compatibility a template-level invariant: fixed
  protected `cardid`/Recovery partitions, retained the five-second UP-key
  Recovery boot hook, and added CI validation for merged-image structure,
  partition MD5/ranges, the 3 MB app limit, and protected payload exclusion.
- Documented a release-title convention for multi-app releases: name tags as `v<version>-<app-name>` (e.g. `v0.1.0-voice-keychain`) so the release title carries the version and the app, and confirm the title after the release is published so a release list is scannable by app.
- Added a post-release follow-up workflow: an `issue-suggestions` skill for filing user feedback as issues against the upstream project, an `experience-pr` skill for submitting reusable development experience as a documentation PR, a `docs/experiences/` directory for per-entry experience files, and supporting `project-completion`, `file-issues`, and experience-index documents.
- Simplified the tracked repository root: moved GitHub-recognized community documents into `.github/`, moved the changelog into `docs/`, updated every reference, and added a root-document allowlist to repository checks.
- Repository-wide language policy: every maintained Markdown default `.md` file is English, Simplified Chinese uses a paired `.zh_CN.md`, and both provide language switches. Static checks reject missing peers, missing switches, and Chinese prose in English defaults.
- Phase one of the AI development workflow: streamlined task-based context routing, unified local/CI validation, added PR checks and a template, and committed the dependency lock for reproducible builds.
- PR review fixes: pinned GitHub Actions to full commit SHAs, split build/release jobs by least privilege, disabled persisted sync checkout credentials, added Feature Request and Usage Question forms, clarified private security-report fallback, and corrected stale README, CI-trigger, and branch descriptions.
- Changed commit titles, PR titles, and PR bodies from Chinese-default to English; updated the Chinese punctuation rule so it no longer applies to PR descriptions.
- Reworked `build-firmware.yml` to pass `SDKCONFIG_DEFAULTS=sdkconfig.defaults`, enable `partitions.csv`, preserve the 8 MB image header, merge a flashable `FoloToy-AI-Passport-full.bin`, publish only that artifact, and use Actions cache v5.
- Integrated upstream PR #6 to resolve PR #4 conflicts: Wi-Fi, Bluetooth LE, radio lifecycle, and low-power demos; a 3 MB factory partition; build/menu/configuration updates; hardware-guide coverage; and bilingual capability tables.
- Defined English imperative Conventional Commit formatting for both commits and PR titles.
- Removed stale sync-workflow template comments and generalized an irrelevant Redis TTL rule to cache components.
- Added Chinese punctuation, credential safety, and recoverable file-deletion conventions.
- Expanded source-comment requirements for functions, state, ownership, concurrency, timing, registers, and magic values.
- Removed AI execution instructions from product READMEs so they remain human-facing product and repository overviews.
- Added `docs/development/agent-guide.md` as the focused AI workflow guide.
- Updated `AGENTS.md`, `docs/INDEX.md`, and the development index for the agent guide.
- Documented why the root README path is reserved for fork owners and how GitHub README precedence supports it.
- Created `main-update` from the upstream-aligned baseline and combined the repository-structure, firmware-CI, and upstream-sync work.
- Corrected the merged documentation index, workflow path, project tree, and CI references.
- Moved CI documentation from software design to `docs/development/`.
- Moved fork-only documentation assets from `assets/docs/` to `docs/assets/`.
- Moved the upstream English/Chinese project READMEs under `docs/` and renamed the documentation catalog to `docs/INDEX.md`.
- Initialized `AGENTS.md`, `CLAUDE.md`, and `CHANGELOG.md`.
- Standardized the initial project README language filenames.
- Added the `docs/`, `assets/`, and `skills/` directory structure.
- Moved the upstream hardware guide into `docs/hardware-design/`.
- Standardized subdirectory README capitalization and introduced fork conventions.
- Allowed fork-owned root README and supplemental documentation content on fork `main`.
- Added and documented the fork-only supplemental-document directory.
- Moved the build CI document to its dedicated CI branch before consolidation.
- Documented clean-`main` reasons, the direct-development exception, and Actions enablement for forks.
- Split the original agent rules into contribution, development, and fork documents with a compact root index.
- Updated software-design and project README references for the new documentation structure.
- Added the documentation catalog and task-triggered routing based on the earlier repository model.
- Added bilingual contribution, code-of-conduct, security, and support documents tailored to this ESP-IDF and fork workflow.
