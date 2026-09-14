[简体中文](THIRD_PARTY.zh_CN.md)

# Third-party sources

## Bloub

- Author: Jérémy Perret.
- Source: https://github.com/jeremy-prt/bloub
- Pinned commit: `b4bb3c1b5f93c7b87a2e8d620f667c4093d97749`.
- License: MIT, retained at `vendor/bloub/LICENSE`.
- Files: unchanged `src/bot/*.ts`, including upstream tests, under `vendor/bloub/src/bot/`.
- Use: the original engine computes baked animation frames. The renderer follows `src/components/BloubBot.vue` mask and layer ordering. Local changes are the monochrome palette, orange notification dot, 192px output, expression hold lengths and device event sequencing; they are outside the vendored engine.

Bloub describes itself as a recreation of the x.ai avatar. This firmware is an independent Codex status display, not an official product of the avatar's original designer or OpenAI. The upstream MIT notice is retained with redistributed source and derived resources.

## miniz

- Source: https://github.com/richgel999/miniz
- Pinned commit: `77d0dce8627735138c51770d1799a1ef48f2117d`.
- License: MIT, retained at `vendor/miniz/LICENSE` and in source headers.
- Use: bounded raw-DEFLATE decoder. Sources/headers are unchanged; the local `miniz_export.h` supplies the static-build export macro. Archive, deflate and zlib compatibility APIs are disabled. The decompressor symbol is prefixed at compile time to avoid the ESP32-C3 ROM miniz ABI; a link-time check rejects an accidental ROM binding.

## Build tools

`tools/package-lock.json` pins esbuild and resvg. They run only during asset generation, not on the device. Their license notices ship with their npm packages. Generated resources and the firmware retain the Bloub source attribution above.

## Montserrat

- Copyright 2011 The Montserrat Project Authors.
- Source: the existing `../codex/assets/fonts/Montserrat-Medium.ttf` in this repository, unchanged.
- License: SIL Open Font License 1.1, copied to `vendor/fonts/OFL.txt`.
- Use: `tools/bake_font.py` rasterizes ASCII outlines at 11/13/18/34/60 px with 16 coverage levels into `main/pet_font.*`. The source hash is recorded in the generated C file. No font engine runs on the board.

## Lucide

The play, coffee and unplug icons come from [Lucide 0.468.0](https://github.com/lucide-icons/lucide/tree/0.468.0/icons). Original SVGs and the ISC notice are retained in `vendor/lucide/`. `tools/bake_icons.mjs` uses the existing resvg build dependency to produce 16×16, four-bit coverage masks (384 bytes total); no SVG runtime is added.

## Selected Zelda audio

The user selected three Nintendo game sound excerpts for this device: Puzzle Solved (L), Sheikah Sensor Ping (N), and Zelda Game Over (T, edited into V1). Community upload sources, selected-preview hashes, resulting WAV hashes and processing details are recorded in [the source manifest](assets/sounds/sources.json). Source pages do not provide a redistribution license; these game assets are not covered by this project's MIT or other software licenses. `assets/sounds/` contains the actual mono PCM inputs used by the deterministic baking tool. V1 preserves the Game Over melody at original speed, transposes it seven semitones, adjusts EQ and removes the tail after 2.25 seconds.
