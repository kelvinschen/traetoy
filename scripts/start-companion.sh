#!/usr/bin/env bash
set -euo pipefail
AI_PASSPORT_WORKSPACE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${AI_PASSPORT_WORKSPACE}/rust-bridge/target/release/passport-bridge" --workspace "${AI_PASSPORT_WORKSPACE}" "$@"
