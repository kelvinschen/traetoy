[English](THIRD_PARTY.md)

# 第三方来源

## Bloub

- 作者：Jérémy Perret。
- 来源：https://github.com/jeremy-prt/bloub
- 固定提交：`b4bb3c1b5f93c7b87a2e8d620f667c4093d97749`。
- 许可：MIT，保存在 `vendor/bloub/LICENSE`。
- 文件：未修改的 `src/bot/*.ts`，包括上游测试，位于 `vendor/bloub/src/bot/`。
- 用途：原引擎计算固件动画帧。绘制遵循 `src/components/BloubBot.vue` 的遮罩与图层顺序。本地调整仅包括黑白配色、橙色通知点、192 像素输出、表情保持时长和设备事件编排，均在原引擎之外实现。

Bloub 将自身描述为 x.ai 形象的复现。本固件是独立的 Codex 状态显示器，不是形象原设计方或 OpenAI 的官方产品。再分发源码和派生资源时保留上游 MIT 声明。

## miniz

- 来源：https://github.com/richgel999/miniz
- 固定提交：`77d0dce8627735138c51770d1799a1ef48f2117d`。
- 许可：MIT，保存在 `vendor/miniz/LICENSE` 和源文件头部。
- 用途：有边界检查的 raw-DEFLATE 解码器。源码和头文件未修改；本地 `miniz_export.h` 提供静态构建的导出宏。禁用归档、压缩和 zlib 兼容 API。编译时给解压函数符号加前缀，避免绑定 ESP32-C3 ROM 中 ABI 不兼容的 miniz，并通过链接检查防止回归。

## 构建工具

`tools/package-lock.json` 固定 esbuild 和 resvg。它们只在生成资源时运行，不在设备上运行。相应许可证包含在 npm 包中。生成资源与固件保留上述 Bloub 来源声明。

## Montserrat

- Copyright 2011 The Montserrat Project Authors。
- 来源：仓库现有的 `../codex/assets/fonts/Montserrat-Medium.ttf`，未修改。
- 许可证：SIL Open Font License 1.1，已复制至 `vendor/fonts/OFL.txt`。
- 用途：`tools/bake_font.py` 将 ASCII 轮廓按 11/13/18/34/60 像素、16 级覆盖率生成 `main/pet_font.*`；生成的 C 文件记录源字体哈希。设备不运行字体引擎。

## Lucide

播放、咖啡杯和断链图标来自 [Lucide 0.468.0](https://github.com/lucide-icons/lucide/tree/0.468.0/icons)。原始 SVG 和 ISC 许可保存在 `vendor/lucide/`；`tools/bake_icons.mjs` 使用已有 resvg 构建依赖生成 16×16 四位抗锯齿遮罩（合计 384 字节），设备无需 SVG 运行时。

## 已选塞尔达音频

用户为该设备选定三段任天堂游戏音效：解谜成功（L）、希卡感应器（N）和 Zelda Game Over（T，编辑为 V1）。社区上传来源、已选试听文件哈希、输出 WAV 哈希与处理细节记录在[来源清单](assets/sounds/sources.json)。来源页面未提供再分发许可；这些游戏素材不适用本项目的软件 MIT 或其他软件许可证。`assets/sounds/` 保存确定性烘焙工具实际使用的单声道 PCM 输入。V1 保留原速 Game Over 旋律，升高七个半音、调整均衡，并截去 2.25 秒之后的尾端。
