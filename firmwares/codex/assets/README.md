<p align="right">
  <a href="README.zh_CN.md">简体中文</a> · <strong>English</strong>
</p>

# Assets

This directory stores reusable fonts, images, music, and sound effects, organized by asset type.

Keep each asset in the matching subdirectory and document its destination, naming, integration method, and source/license. Do not mix binary assets with Markdown documentation.

## Fonts

Store reusable font files and generated font sources in `fonts/`.

- Use descriptive names that include the family, weight, size, and format when relevant.
- Document the source, license, character range, conversion command, and expected destination.
- Check Flash and internal-RAM impact before adding a font; the ESP32-C3 has no PSRAM.
- Do not commit fonts whose license does not permit redistribution.

## Images

Store reusable source images and generated display assets in `images/`.

- Use descriptive names and document dimensions, pixel format, conversion steps, and destination.
- Prefer formats suitable for the 240 × 320 RGB565 display and account for Flash and internal RAM.
- Preserve editable sources where licensing permits, and record the source and license.
- Never commit device QR secrets, credentials, or personal data in images.

## Music and sound effects

Store reusable music and sound-effect sources in `music/`.

- Document the source, license, sample rate, bit depth, channels, conversion command, and destination.
- Prefer 16 kHz, 16-bit mono PCM when it matches the current BSP audio path.
- Check Flash and internal-RAM cost before embedding audio; stream or chunk long recordings.
- Do not commit media without redistribution permission.

### Codex application icon

`images/codex-official-light.png` is the unmodified icon copied from the installed official ChatGPT application, `Contents/Resources/icon-codex-light.png`. OpenAI trademark asset, used here for local product identification; not an original project asset or a grant of redistribution rights. `scripts/generate-logo.py` in the parent workspace converts it to the 32x32 BGRA8888 source `main/codex_logo.c` (4 KiB).

### Battery digits

`fonts/Montserrat-Medium.ttf` is the unmodified font from [LVGL v9.2.2](https://github.com/lvgl/lvgl/blob/v9.2.2/scripts/built_in_font/Montserrat-Medium.ttf), licensed under SIL OFL 1.1 (`fonts/Montserrat-OFL.txt`). `fonts/montserrat_medium_13_digits.c` contains only digits and a hyphen, generated with `lv_font_conv@1.5.3` at 13 px, 4 bpp, without compression. The command is recorded in the generated file header. `main/CMakeLists.txt` compiles it directly; glyph data stays in Flash, with no new framebuffer or runtime font engine. The subset's nine-pixel ink height is centered within the battery interior.

`fonts/montserrat_medium_13_ascii.c` uses the same licensed source and converter, with ASCII U+0020..U+007E at 13 px / 4 bpp. It supplies the secondary labels and chart dates; the complete command is in its generated header. It is compiled directly by `main/CMakeLists.txt`.

`fonts/montserrat_medium_11_usage.c` is an 11 px / 4 bpp subset of the same Montserrat source for compact daily bar values (digits, decimal point, unit suffixes and hyphen). It is compiled directly, stores glyphs in Flash, and adds no framebuffer. The generation command is recorded in its header.

The horizontal daily-usage view uses the existing 13 px ASCII font for dates, values and units. The 11 px usage, 12 px numeric and 8/9 px unit subsets are retained as historical assets and are no longer compiled into the app.

`fonts/Montserrat-Bold.ttf` comes from the [Montserrat project](https://github.com/JulietaUla/Montserrat/blob/master/fonts/ttf/Montserrat-Bold.ttf) under SIL OFL 1.1 (`fonts/Montserrat-Bold-OFL.txt`). `fonts/montserrat_bold_16_ascii.c` is its 16 px / 4 bpp ASCII subset, generated with `lv_font_conv@1.5.3`; the command is in the header. It supplies real bold reset-count and countdown values and is compiled directly, with glyphs stored in Flash.

The auxiliary-page labels use `fonts/noto_info_16.c`, a 16 px, 4 bpp subset of Noto Sans CJK SC Regular, licensed under SIL OFL 1.1 (`fonts/NotoSansCJK-OFL.txt`). Source: https://github.com/notofonts/noto-cjk/blob/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf . Generated with `lv_font_conv@1.5.3 --no-compress --no-prefilter --bpp 4 --size 16 -r 0x20-0x7E`, plus the CJK characters used by `main/companion_info_ui.c`, font name `companion_info_font`. Only generated glyphs are bundled; the full source font is not copied into the firmware.
