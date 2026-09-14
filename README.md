[简体中文](README.zh_CN.md)

# Traetoy

Traetoy is independent, open-source companion software and firmware for
FoloToy AI Passport hardware. It combines ESP32-C3 firmware, a macOS menu-bar
application, and a local Rust bridge that can show Codex task and account
status over USB or authenticated BLE.

Traetoy is not published by, affiliated with, or endorsed by FoloToy or
OpenAI. It provides software compatibility for an existing retail device; it
does not publish hardware designs, original device backups, or product visual
assets.

## What is included

- firmware workspaces for the Codex dashboard and Codex Pet;
- shared board support for the AI Passport display, audio, input, battery,
  partition, recovery, and BLE contracts;
- a macOS menu-bar application, Rust bridge, local/SSH hook receivers, and
  host tests; and
- source-only build and validation tooling.

The initial public release contains no prebuilt firmware artifacts. Do not
erase a device or directly flash a merged image. Use the protected installer
only after reviewing its device and backup checks.

## Build from source

Use macOS for the companion application and ESP-IDF 5.5.3 for firmware builds.
Create a local Python environment, install the pinned host dependencies, then
run the checks that apply to your change:

~~~sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cargo test --manifest-path rust-bridge/Cargo.toml
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/firmware.py build codex
.venv/bin/python scripts/firmware.py build codex-pet
~~~

See the [developer guide](docs/development.md), [firmware workspace guide](docs/firmware-workspaces.md), and [hooks guide](docs/hooks.md) for setup and validation. Copy
config/bridge.example.json to the ignored local path config/bridge.json before
configuring optional SSH hosts.

## Privacy and security

The bridge processes task titles, project labels, timing, quota summaries, and
local device state. It is designed not to send prompts, tool arguments,
answers, or account credentials to the device. Read [PRIVACY.md](PRIVACY.md)
before enabling remote hosts or attaching a shared device.

Never commit local configuration, BLE pairing material, device backups,
database files, reports, or logs. See [SECURITY.md](SECURITY.md) to report a
vulnerability privately.

## License, provenance, and known material

Original Traetoy source is MIT licensed; see [LICENSE](LICENSE). FoloToy board
support and the firmware baseline retain their upstream MIT notices. Fonts and
vendored dependencies keep their original notices in place.

[NOTICE](NOTICE) and [ASSET_PROVENANCE.md](ASSET_PROVENANCE.md) record each
material source. The repository intentionally retains a Codex trademark icon
and selected Nintendo game audio for which no redistribution permission has
been identified. They are not Traetoy assets, are not represented as licensed
or authorized, and may need to be removed after a rights-holder request.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and [SUPPORT.md](SUPPORT.md) before participating. Contributions are
made under the root MIT license and must not include private data or
unlicensed material.
