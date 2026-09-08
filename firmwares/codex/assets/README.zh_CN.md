<p align="right">
  <strong>简体中文</strong> · <a href="README.md">English</a>
</p>

# 资源目录（Assets）

本目录集中存放可复用的资源（字库、图片、音乐等），按资源类型分子目录管理。每个资源放在其类型对应的子目录，并记录放置路径、命名方式、集成方式与来源/许可。二进制资源（字体、图片、音频）不属于纯 markdown 文档，请勿与文档混放。涉及版权/授权的资源需注明来源与许可。

## 字库（fonts）

可复用的字库文件与生成的字库源码放在 `fonts/`。

- 命名要能反映字族、字重、字级与格式。
- 记录来源、许可、字符范围、转换命令与目标放置路径。
- 添加字库前评估 Flash 与内部 RAM 影响；ESP32-C3 无 PSRAM。
- 不提交许可不允许分发的字库。

## 图片（images）

可复用的源图与生成的显示资产放在 `images/`。

- 使用描述性命名，并记录尺寸、像素格式、转换步骤与目标路径。
- 优先采用适合 240 × 320 RGB565 显示的格式，并纳入 Flash 与内部 RAM 考量。
- 许可允许时保留可编辑源文件，并记录来源与许可。
- 图片中不得包含设备二维码秘密、凭证或个人数据。

## 音乐与音效（music）

可复用的音乐与音效源码放在 `music/`。

- 记录来源、许可、采样率、位深、声道、转换命令与目标路径。
- 与当前 BSP 音频路径匹配时优先采用 16 kHz、16 位单声道 PCM。
- 嵌入音频前评估 Flash 与内部 RAM 成本；长录音应流式或分块。
- 无再分发许可不提交媒体文件。

### Codex 应用图标

`images/codex-official-light.png` 原样复制自已安装的官方 ChatGPT 应用 `Contents/Resources/icon-codex-light.png`。这是 OpenAI 商标素材，用于本地产品识别，并非本项目原创素材，也不代表授予再分发权限。父工作区的 `scripts/generate-logo.py` 将其转换为 32×32 BGRA8888 源码 `main/codex_logo.c`（4 KiB）。

### 电池数字

`fonts/Montserrat-Medium.ttf` 原样取自 [LVGL v9.2.2](https://github.com/lvgl/lvgl/blob/v9.2.2/scripts/built_in_font/Montserrat-Medium.ttf)，遵循 SIL OFL 1.1（`fonts/Montserrat-OFL.txt`）。`fonts/montserrat_medium_13_digits.c` 仅包含数字和连字符，用 `lv_font_conv@1.5.3` 生成 13 px、4 bpp、未压缩字体，生成命令保留在文件头。`main/CMakeLists.txt` 直接编译该文件；字形数据存放于 Flash，不新增帧缓冲或运行时字体引擎。子集实际字形高九像素，在电池内部居中。

`fonts/montserrat_medium_13_ascii.c` 使用相同授权字体源和转换器，包含 13 px／4 bpp 的 ASCII U+0020..U+007E，供图表次级文字和日期标签使用。完整命令保留在生成文件头，由 `main/CMakeLists.txt` 直接编译。

`fonts/montserrat_medium_11_usage.c` 使用同一 Montserrat 字源生成 11 px / 4 bpp 子集，用于柱顶每日简写数值（数字、小数点、单位和连字符）。直接编译，字形存储于 Flash，不新增帧缓冲；生成命令记录于文件头。

横向每日用量视图使用现有 13 px ASCII 字体绘制日期、数值与单位。11 px 用量、12 px 数字及 8/9 px 单位子集保留为历史素材，不再编译进应用。

`fonts/Montserrat-Bold.ttf` 来自 [Montserrat 项目](https://github.com/JulietaUla/Montserrat/blob/master/fonts/ttf/Montserrat-Bold.ttf)，采用 SIL OFL 1.1 授权（`fonts/Montserrat-Bold-OFL.txt`）。`fonts/montserrat_bold_16_ascii.c` 是使用 `lv_font_conv@1.5.3` 生成的 16 px / 4 bpp ASCII 子集，命令记录在文件头。用于重置卡数量和倒计时的真正粗体，直接编译，字形存于 Flash。

辅助页面标签使用 `fonts/noto_info_16.c`：Noto Sans CJK SC Regular 的 16 px、4 bpp 子集，采用 SIL OFL 1.1 许可（`fonts/NotoSansCJK-OFL.txt`）。来源：https://github.com/notofonts/noto-cjk/blob/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf 。生成参数为 `lv_font_conv@1.5.3 --no-compress --no-prefilter --bpp 4 --size 16 -r 0x20-0x7E`，另加入 `main/companion_info_ui.c` 使用的汉字，字体名 `companion_info_font`。固件仅包含生成的字形，不复制完整源字体。
