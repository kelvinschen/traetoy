#!/usr/bin/env bash
# Source this file from a shell to activate the workspace-local ESP-IDF.
AI_PASSPORT_WORKSPACE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export IDF_TOOLS_PATH="${AI_PASSPORT_WORKSPACE}/.toolchains/espressif"
source "${AI_PASSPORT_WORKSPACE}/.toolchains/esp-idf/export.sh"
export ACTIONLINT_BIN="${AI_PASSPORT_WORKSPACE}/.venv/bin/actionlint"
