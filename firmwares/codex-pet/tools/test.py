#!/usr/bin/env python3
"""Host gate: source morph continuity, all C frames vs Python zlib, behavior and protocol."""

from pathlib import Path
import json, subprocess, tempfile, zlib, sys

ROOT = Path(__file__).resolve().parents[1]
CODEX = ROOT.parent / "codex/main"
subprocess.run(["node", str(ROOT / "tools/test_sequences.mjs")], check=True)
subprocess.run([sys.executable, str(ROOT / "tools/bake_sound.py"), "--check"], check=True)
with tempfile.TemporaryDirectory(prefix="pet-tests-") as tmp:
    exe = Path(tmp) / "test-pet"
    flags = [
        "-std=c11",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-DCOMPANION_ALERT_KIND_MAX=3",
        "-DMINIZ_NO_ARCHIVE_APIS",
        "-DMINIZ_NO_DEFLATE_APIS",
        "-DMINIZ_NO_ZLIB_APIS",
        "-DMINIZ_NO_STDIO",
        "-Dtinfl_decompress=pet_tinfl_decompress",
    ]
    sources = [
        ROOT / "tests/test_pet.c",
        *[
            ROOT / "main" / n
            for n in ["pet_assets.c", "pet_font.c", "pet_codec.c", "pet_behavior.c", "pet_ui.c", "pet_pages.c", "pet_sound_pcm.c"]
        ],
        *[CODEX / n for n in ["companion_protocol.c", "companion_alerts.c"]],
        *[ROOT / "vendor/miniz" / n for n in ["miniz.c", "miniz_tinfl.c"]],
    ]
    subprocess.run(
        [
            "cc",
            *flags,
            *[f"-I{p}" for p in [ROOT / "main", CODEX, ROOT / "vendor/miniz"]],
            *map(str, sources),
            "-lm",
            "-o",
            str(exe),
        ],
        check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "tools/check_link.py"), "nm", str(exe)], check=True
    )
    result = subprocess.check_output(
        [str(exe), str(ROOT / "assets/bloub.bin"), *sys.argv[1:]], text=True
    )
    print(result.strip())
    data = (ROOT / "assets/bloub.bin").read_bytes()
    manifest = json.loads((ROOT / "assets/bloub.json").read_text())
    checksum = 0
    count = 0
    for clip in manifest["clips"]:
        pixels = bytes([238]) * (manifest["width"] ** 2 // 2)
        decoded = []
        for f in clip["frames"]:
            delta = zlib.decompress(data[f["offset"] : f["offset"] + f["size"]], -15)
            pixels = delta if f["key"] else bytes(a ^ b for a, b in zip(pixels, delta))
            decoded.append(pixels)
            checksum = zlib.crc32(pixels, checksum)
            count += 1
        if clip.get("loop") or clip.get("tail"):
            start = 0 if clip.get("loop") else round(clip["reaction"] * 60)
            assert decoded[-1] == decoded[start], clip["name"] + " seam"
    assert f"CRC {checksum:08x} FRAMES {count} LOGIC PASS" in result
    print(
        f"PASS: {count} source frames, random seeks, dirty stripe coverage, tiled rendering, bounds, alert deduplication, immutable snapshots, quota selection and behavior"
    )
