#!/usr/bin/env python3
"""Generate the deterministic CycloneDX inventory committed with Traetoy."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote
import uuid


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "SBOM.cdx.json"


def component(name, version, ecosystem, *, license_name=None, source=None):
    item = {
        "type": "library",
        "name": name,
        "version": str(version),
        "purl": f"pkg:{ecosystem}/{quote(name, safe='/-._')}@{quote(str(version), safe='.-_')}",
    }
    if license_name:
        item["licenses"] = [{"license": {"name": license_name}}]
    if source:
        item["externalReferences"] = [{"type": "distribution", "url": source}]
    return item


def python_components():
    items = []
    for raw in (ROOT / "requirements.txt").read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, version = line.split("==", 1)
        items.append(component(name, version, "pypi"))
    return items


def cargo_components():
    packages = []
    current = None
    for raw in (ROOT / "rust-bridge" / "Cargo.lock").read_text().splitlines():
        if raw == "[[package]]":
            if current:
                packages.append(current)
            current = {}
            continue
        if current is None:
            continue
        match = re.match(r'^(name|version|source) = "(.*)"$', raw)
        if match:
            current[match.group(1)] = match.group(2)
    if current:
        packages.append(current)
    items = []
    for package in packages:
        if "name" not in package or "version" not in package:
            continue
        source = package.get("source")
        ecosystem = "cargo" if source else "generic"
        items.append(component(package["name"], package["version"], ecosystem, source=source))
    return items


def npm_components():
    lock = json.loads((ROOT / "firmwares" / "codex-pet" / "tools" / "package-lock.json").read_text())
    items = []
    for location, package in lock.get("packages", {}).items():
        if not location or not package.get("version"):
            continue
        name = package.get("name") or location.rsplit("node_modules/", 1)[-1]
        items.append(component(name, package["version"], "npm", source=package.get("resolved")))
    return items


def idf_components(lock_path):
    items = []
    current = None
    for raw in lock_path.read_text().splitlines():
        match = re.match(r"^  ([^:\s]+(?:/[^:\s]+)?):$", raw)
        if match:
            current = match.group(1)
            continue
        version = re.match(r"^    version: ['\"]?([^'\"]+)['\"]?$", raw)
        if current and version:
            items.append(component(current, version.group(1), "generic"))
            current = None
    return items


def provenance_components():
    return [
        component(
            "FoloToy AI Passport board and firmware baseline",
            "042a5d59da54cc717bdfd08cc99131bc50526341",
            "generic",
            license_name="MIT",
            source="https://github.com/FoloToy/ai-passport",
        ),
        component("Montserrat", "1.0", "generic", license_name="OFL-1.1"),
        component("Noto Sans CJK", "1.0", "generic", license_name="OFL-1.1"),
        component(
            "Bloub",
            "b4bb3c1b5f93c7b87a2e8d620f667c4093d97749",
            "generic",
            license_name="MIT",
            source="https://github.com/jeremy-prt/bloub",
        ),
        component(
            "miniz",
            "77d0dce8627735138c51770d1799a1ef48f2117d",
            "generic",
            license_name="MIT",
            source="https://github.com/richgel999/miniz",
        ),
        component("Lucide", "0.468.0", "generic", license_name="ISC"),
    ]


def inventory():
    components = (
        python_components()
        + cargo_components()
        + npm_components()
        + idf_components(ROOT / "firmwares" / "codex" / "dependencies.lock")
        + idf_components(ROOT / "firmwares" / "codex-pet" / "dependencies.lock")
        + provenance_components()
    )
    unique = {}
    for item in components:
        unique[(item["purl"], item["name"], item["version"])] = item
    return [unique[key] for key in sorted(unique)]


def document():
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'https://github.com/traetoy/traetoy/sbom')}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "traetoy",
                "version": "source",
                "licenses": [{"license": {"id": "MIT"}}],
            }
        },
        "components": inventory(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed SBOM is stale")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    content = json.dumps(document(), indent=2, sort_keys=True) + "\n"
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if args.check:
        if not output.exists() or output.read_text() != content:
            print(f"SBOM is stale: {output.relative_to(ROOT)}", file=sys.stderr)
            return 1
        print(f"SBOM is current: {output.relative_to(ROOT)}")
        return 0
    output.write_text(content)
    print(f"Wrote {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
