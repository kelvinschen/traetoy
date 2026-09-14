#!/usr/bin/env python3
"""Check the public-source candidate for private files and common secrets."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "LICENSE",
    "NOTICE",
    "ASSET_PROVENANCE.md",
    "ASSET_PROVENANCE.zh_CN.md",
    "PRIVACY.md",
    "PRIVACY.zh_CN.md",
    "SECURITY.md",
    "SECURITY.zh_CN.md",
    "CONTRIBUTING.md",
    "CONTRIBUTING.zh_CN.md",
    "CODE_OF_CONDUCT.md",
    "CODE_OF_CONDUCT.zh_CN.md",
    "SUPPORT.md",
    "SUPPORT.zh_CN.md",
    "SBOM.cdx.json",
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/firmware.yml",
    ".github/workflows/secret-scan.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/usage_question.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "shared/boards/ai-passport/LICENSE",
    "firmwares/codex/LICENSE",
    "firmwares/codex-pet/THIRD_PARTY.md",
    "firmwares/codex-pet/vendor/bloub/LICENSE",
    "firmwares/codex-pet/vendor/fonts/OFL.txt",
    "firmwares/codex-pet/vendor/lucide/LICENSE",
    "firmwares/codex-pet/vendor/miniz/LICENSE",
    "firmwares/codex/assets/images/codex-official-light.png",
    "firmwares/codex/main/codex_logo.c",
    "firmwares/codex-pet/assets/sounds/sources.json",
)
PRIVATE_PATHS = (
    "backups/",
    "reports/",
    ".venv/",
    ".toolchains/",
    "config/bridge.json",
    "config/ble-device.json",
)
PRIVATE_SUFFIXES = (".pem", ".key")
SECRET_PATTERNS = {
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}"),
    "OpenAI-style key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
}


def candidates():
    """Return the exact file set that `git add -A` would publish.

    Use a disposable index so this audit neither stages user work nor reports a
    deleted path that remains only in the real index.
    """
    index = subprocess.run(
        ["git", "rev-parse", "--git-path", "index"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    index_path = (ROOT / index).resolve() if not Path(index).is_absolute() else Path(index)
    with tempfile.TemporaryDirectory(prefix="traetoy-release-audit-") as directory:
        temporary_index = Path(directory) / "index"
        if index_path.exists():
            shutil.copy2(index_path, temporary_index)
        environment = os.environ | {"GIT_INDEX_FILE": str(temporary_index)}
        subprocess.run(["git", "add", "-A"], cwd=ROOT, env=environment, check=True)
        result = subprocess.run(
            ["git", "ls-files", "-z", "--cached"],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
        )
    return [Path(value.decode()) for value in result.stdout.split(b"\0") if value]


def fail(message, failures):
    print(f"FAIL: {message}", file=sys.stderr)
    failures.append(message)


def main():
    failures = []
    for required in REQUIRED:
        if not (ROOT / required).is_file():
            fail(f"missing required public-release file: {required}", failures)

    files = candidates()
    for path in files:
        value = path.as_posix()
        if value.startswith(PRIVATE_PATHS) or value.endswith(PRIVATE_SUFFIXES):
            fail(f"private or key material is a release candidate: {value}", failures)

    for root_readme in (ROOT / "README.md", ROOT / "README.zh_CN.md"):
        if root_readme.exists():
            text = root_readme.read_text()
            for prohibited in ("reports/", "backups/", "devbox"):
                if prohibited in text:
                    fail(f"root README exposes local-only reference {prohibited}", failures)

    for path in files:
        absolute = ROOT / path
        if not absolute.is_file() or absolute.stat().st_size > 1_000_000:
            continue
        try:
            text = absolute.read_text()
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            for line, value in enumerate(text.splitlines(), start=1):
                if pattern.search(value):
                    fail(f"{label} candidate in {path}:{line}", failures)

    provenance = ROOT / "ASSET_PROVENANCE.md"
    if provenance.exists():
        required_phrases = (
            "No redistribution permission has been identified",
            "publisher risk acceptance",
            "Codex icon",
            "Selected game audio",
            "FoloToy AI Passport",
        )
        text = provenance.read_text()
        for phrase in required_phrases:
            if phrase not in text:
                fail(f"asset provenance lacks required restricted-material disclosure: {phrase}", failures)

    license_text = (ROOT / "LICENSE").read_text() if (ROOT / "LICENSE").exists() else ""
    if "MIT License" not in license_text or "Copyright (c) 2026 Traetoy contributors" not in license_text:
        fail("root LICENSE does not contain the approved MIT notice", failures)

    notice_text = (ROOT / "NOTICE").read_text() if (ROOT / "NOTICE").exists() else ""
    for phrase in ("FoloToy", "Montserrat", "Bloub", "Codex brand artwork", "Nintendo audio"):
        if phrase not in notice_text:
            fail(f"NOTICE lacks expected provenance reference: {phrase}", failures)

    sbom_path = ROOT / "SBOM.cdx.json"
    if sbom_path.exists():
        try:
            sbom = json.loads(sbom_path.read_text())
        except json.JSONDecodeError as error:
            fail(f"SBOM is not valid JSON: {error}", failures)
        else:
            metadata = sbom.get("metadata", {}).get("component", {})
            names = {item.get("name") for item in sbom.get("components", [])}
            if metadata.get("name") != "traetoy" or metadata.get("licenses") != [{"license": {"id": "MIT"}}]:
                fail("SBOM metadata does not identify the MIT Traetoy source release", failures)
            for name in ("FoloToy AI Passport board and firmware baseline", "Montserrat", "Noto Sans CJK", "Bloub", "miniz", "Lucide"):
                if name not in names:
                    fail(f"SBOM lacks expected declared component: {name}", failures)

    if failures:
        return 1
    print(f"PASS: audited {len(files)} files in the pending public-release candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
