[简体中文](CONTRIBUTING.zh_CN.md)

# Contributing

Thank you for improving Traetoy. Contributions are accepted under the root MIT
license. Do not submit material you do not have the right to redistribute.

## Before opening a pull request

- Read README.md, PRIVACY.md, NOTICE, and ASSET_PROVENANCE.md.
- Keep English and Simplified Chinese maintained documentation paired.
- Do not commit credentials, pairing keys, private SSH configuration, backups,
  device identities, user data, or unsanitized logs.
- Preserve the USB/BLE compatibility contract and do not erase or directly
  flash a merged image to a device.

## Validation

Run the relevant checks from the repository root:

    cargo test --manifest-path rust-bridge/Cargo.toml
    .venv/bin/python -m unittest discover -s tests -v
    .venv/bin/python scripts/firmware.py build codex
    .venv/bin/python scripts/firmware.py build codex-pet

Report Build, Host tests, Device tests, and Unverified separately. A successful
build is not a device test.

## Pull requests

Keep each pull request focused. Describe user-visible behavior, compatibility
impact, validation performed, and any unverified hardware work. Use the
security reporting process for vulnerabilities rather than public issues.
