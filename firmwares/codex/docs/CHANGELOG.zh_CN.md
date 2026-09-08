<p align="right">
  <strong>简体中文</strong> · <a href="CHANGELOG.md">English</a>
</p>

# Changelog

## Unreleased

- 增加 USB/BLE 共用的 Passport 固件身份与能力查询，支持原生菜单栏管理；保持 Codex 页面、提醒和省电行为。

- 完成页工作区改为独占 170 px 宽的一行，保留 16 px 字号；主机名与耗时移至下一行。图片保持 3200 字节，主机信息随提醒独立保存，避免项目名提前截断。

- 增加主屏上下键切换重置卡与连接状态。重置卡按到期时间排序，详情显示发放／过期日期、时区和说明，不执行兑换。复用现有额度与数据源采集，仅在变化时发送有界辅助元数据；关闭提醒后返回原功能页。

- 完成页项目／主机文字从 13 px 增至 16 px，复用两块 84×16 位图，保持标题字形。提醒诊断改用正式 Rust 位图。

- 完成页改为标题优先布局：小状态勾、细分隔线、橙色文件夹图标、上下排列的项目／主机名及右对齐耗时。元数据仍复用同一提醒位图和现有像素缓冲。

- 连续一小时无新提醒时自动息屏，手动唤醒重新计时；任意功能键仅唤醒不导航，新完成提醒自动亮屏。息屏期间暂停提醒可见计时和画面重绘，连接与采集继续运行。

- 根据实屏反馈将闲置背光恢复为 35%，活跃亮度保持 75%。

- 无按键或新提醒 60 秒后，闲置背光占空比从 35% 下调到 15%；按键或新提醒仍恢复至 75%。

- 移除重置卡背景与叠卡装饰；重置卡和倒计时统一采用右对齐的灰色标题、深黑色 16 px 粗体数值。

- 重置卡块移至右上方，右对齐的重置倒计时放在其下方，保留可选第二额度窗口的空间。

- 重置倒计时靠右对齐，与左侧圆环形成两端布局；重置卡块上移 8 px，并在双额度窗口时保留额外文字空间。

- 移除顶部状态栏分隔线，重置倒计时移至右上方，下方展示可用重置卡。通过已有账号轮询读取数量，未知或过期时显示 `--`。

- 额度圆环直径由 86 px 放大至 100 px、线宽调整为 7 px，利用每日用量区上方留白，保持百分比居中。

- 将额度数字和横向进度条改为静态 270 度开口圆环，百分比居中、重置倒计时放右侧。保留七行用量，额度过期时显示空环。

- 每日用量横条统一使用橙色，移除按用量着色的逻辑。

- 每日用量按最新日期在上排列；横条按七日窗口内的相对用量，从浅橙、橙色到深橙红着色，移除最新日期的特殊高亮。

- 每日用量改为七行横向布局：MM/DD 日期、比例横条、右对齐用量。移除周汇总，数字和单位采用统一字号。

- 每日用量数字统一使用 12 px、单位使用 9 px，保持基线对齐，并采用 34 px 列宽保留间距。

- 每日用量数字放大到 13 px（较宽数值使用 12 px），单位后缀改为 8 px 并与数字基线对齐，保持自然字间距和七列布局。

- 七日柱底改为 Mon 至 Sun 三字母星期标签，不再展示日期。

- 恢复每日用量数字的自然字间距，将七列各自拓宽到 33 像素，改善小字可读性。

- 将用量折线改为七日柱形图，柱顶展示简写数值、柱底展示日期；突出最新一天，并将 `7d` 与总量紧邻显示。保留缺失与零值语义，扩展元数据传输逐日标签。

- 移除 TOKENS 标题，放宽两项用量摘要；折线增加零基线与向上取整的上界标签。重置倒计时不足 24 小时时保持小时／分钟或分钟格式。

- 将额度重置时间移至百分比右侧；Today 与 7d 合为一行，下方展示静态七天每日用量折线。缺失日期保留断点，兼容扩展元数据以传输归一化图表点。

- 伴侣同一时刻只保持一种传输连接：USB 接管时关闭 BLE，仅在没有可用 USB 时连接蓝牙；顶部只显示当前接口图标。

- 打开伴侣串口时保留 USB 控制线状态，避免 USB 接管触发复位、丢失设备状态。电池微调为 32 × 16 像素，数字使用 13 px 抗锯齿字体。
- 电池调整为 32 × 16 像素，电量数字放入图标内并省略百分号并随填充区域反色。每条提醒累计展示 30 秒后自动确认，被打断后继续剩余时间，栈清空后返回原页面。

- 伴侣主循环改为输入／数据到来时唤醒，替代 100 毫秒轮询；跳过未变化的显示值与分钟内耗时更新。一分钟无操作后背光从 75% 降至 35%，按键按下或新提醒立即恢复，电量采样改为每 30 秒一次。

- 新增经过认证的 BLE 传输：通过 USB 配对，支持有界分片、防重放和顶部连接图标，保留 USB 备用通道。压缩标题缓存并复用画布，在无 PSRAM 条件下为 BLE 协议栈腾出内存。

- 未确认任务提醒改为最多八条的后进先出栈：短按确定键确认一条，长按返回主页并保留提醒，主页确定键优先打开未确认提醒，顶部显示数量；满容量时淘汰最旧提醒。

- 完成提醒改为左侧小勾、右侧任务详情：最多三行标题、耗时和工作区；移除提醒页额度摘要，复用现有图像内存。

- USB 连接状态移至顶部小图标，收紧底部任务状态条，为 token 统计留出更多空间。

- 运行任务增加工作区／项目名，Git 工作树映射至原项目；耗时简化为无前缀的分钟级显示，USB 刷新间隔调整为三秒。

- 新增带统计日期的账号 token 用量（单日及近七天）、任务本轮耗时、四级灰度抗锯齿中文标题和更大的详情字号；音量设为 100%，移除重复额度说明。

- 移除额度动效，电池图标按电量计的实时百分比填充，并在启动后立即读取电量。

- 额度改为连续圆角实色进度条，数值变化平滑过渡 600 毫秒，末端每三秒轻微呼吸；移除密集刻度。

- 将配件界面改为 PAPER METER，使用官方 Codex 图标，支持中文任务标题浏览和长按确定键返回；移除声音开关和底部按键提示。

- 隐藏没有额度数据的窗口，并让任务状态上移使用空出的空间。

- 新增 USB Codex 状态页，支持额度时效、任务完成提示、静音／关闭提示按键和串口协议校验。
- 加入厂家为优特利 520mAh 电芯生成的 80 字节 CW2017 profile，并实现内容与更新标志检查、写入后校验、规定的重启时序以及有上限的 SOC 就绪等待。

- 按功能域整理文档并采用双入口：根目录 `AGENTS.md` 变为薄路由（只保留硬约束与任务路由），详细的 AI 开发工作流下沉到 `docs/development/ai-guide.md`，`agent-guide.md` 并入其中。为 `docs/development/` 增加二级分区（`engineering/`、`ci/`、`release/`），把 `plays/` 应用档案与 `experiences/` 移入带专属 README 的 `docs/reference/` 参考区；删除 `docs/software-design/`（空脚手架）；把 `assets/{fonts,images,music}/README` 三个叶子 README 并入 `assets/` README；把 `project-completion` 的六个子文档压平为单文件；并把每个目录统一为单一 README，消除所有 `INDEX` 文件与一处重复经验索引。所有交叉引用与文献链接已更新；未丢弃任何内容。

- 将小程序 BLE 安装兼容提升为二创模板强制契约：固定保护 `cardid`/Recovery 分区，
  保留上键持续 5 秒进入 Recovery 的 bootloader hook，并在 CI 强制校验合并镜像结构、
  分区表 MD5/范围、3 MB 应用上限和保护分区数据不入包。
- 规定多应用发布的 Release 标题约定：tag 按 `v<版本>-<应用名>`（如 `v0.1.0-voice-keychain`）命名，让 Release 标题同时带版本与应用名；发布成功后核对标题，保证一眼扫 Release 列表就能区分是哪个应用。
- 新增发布后收尾流程：`issue-suggestions` skill 用于把用户反馈作为 issue 提交到上游项目；`experience-pr` skill 用于把可复用的开发经验作为文档 PR 提交；新增 `docs/experiences/` 目录保存单条经验文件；并配套 `project-completion`、`file-issues` 与经验索引文档。
- 精简仓库根目录：将 GitHub 可识别的社区治理文档迁入 `.github/`，将变更记录迁入 `docs/`，同步全部引用，并在仓库检查中加入根目录文档白名单。
- 全仓库文档语言规范：所有维护中的 Markdown 默认 `.md` 文件使用英文，简体中文使用配对的 `.zh_CN.md`，双方提供语言切换；静态检查会阻止缺失配对、缺失切换链接或英文默认页混入中文正文。
- AI 开发流程一期：精简按任务加载的上下文入口，统一本地/CI 验证脚本，新增 PR 自动构建与模板，并提交依赖锁文件以提高构建可复现性。
- PR 审查修复：GitHub Actions 固定到完整 commit SHA，构建与发布 job 按最小权限拆分，同步 checkout 关闭凭证持久化；补充 Feature Request / Usage Question issue 表单；启用并修正私密安全报告兜底说明；清理 README 路径、CI 触发条件与历史分支描述漂移。
- 语言规范变更：commit 标题、PR 标题与 body 由"默认中文"改为**使用英文**（`docs/contribution/commit-and-pr.md` 更新）；中文写作规范（全角标点）适用范围剔除 PR/MR 描述（`doc-conventions.md` 更新）。
- CI 构建改造：`build-firmware.yml` 显式传入 `SDKCONFIG_DEFAULTS=sdkconfig.defaults` 再 `idf.py build`，由 defaults 启用自定义分区表（`CONFIG_PARTITION_TABLE_CUSTOM=y`，文件名为 `partitions.csv`）；`CONFIG_ESPTOOLPY_HEADER_FLASHSIZE_UPDATE` 改为 `n`，再用 `idf.py merge-bin -o build/FoloToy-AI-Passport-full.bin` 合并可直刷完整固件；产物精简为仅 full.bin；`actions/cache` 升级到 v5 以消除 GitHub Actions Node.js 20 弃用警告；CI 文档同步更新。
- 合并上游 PR #6（wireless-low-power-demos）以解决 PR #4 冲突：引入无线/低功耗 demo（`main/demo_wifi.c`、`demo_ble.c`、`demo_radio.c`、`demo_low_power.c`）、`partitions.csv`（NVS/PHY/3 MB factory-app 分区）、`main/CMakeLists.txt`/`main.c`/`demo.h`/`sdkconfig.defaults` 更新；同步硬件指南的 Wi-Fi/BLE/低功耗章节；README 能力契约表补充 Wi-Fi/Bluetooth LE/Low power 三项（中英双语）。
- 提交规范补充：`docs/contribution/commit-and-pr.md` 明确 PR 标题与 commit 标题使用相同的 Conventional Commit 格式和英文祈使句，不用名词短语当标题。
- CI 与文档清理：`sync-main.yml` 移除 `test_mode` 残留模板注释；`docs/development/coding-conventions.md` 将「Redis TTL」条目泛化为「缓存组件」条目（当前固件无 TTL 约束需求，消除从模板带入的无关约定）。
- 补充通用规范（借鉴 Shinku）：`docs/contribution/doc-conventions.md` 新增中文全角标点规范（正文 `，`；`（`）`，代码/命令/路径保留英文原样）、凭证不入仓规范（token/密钥/私钥绝不入仓，提交前 git diff 扫描敏感前缀）、文件删除安全规范（删除走系统回收站，不用 rm -rf/git clean -fd）。
- 代码注释规范强化：`docs/development/coding-conventions.md` 补充完善注释要求——函数说明（用途/参数/返回值/副作用/线程上下文/内存所有权/初始化顺序）、变量说明（语义/取值范围/生命周期/同步要求）、逻辑注释（状态机/时序/寄存器/魔数依据），覆盖范围宁多勿少，中文注释保留英文技术术语。
- 文档去 AI 化：`docs/README.md` / `docs/README.zh_CN.md` 移除 AI 专属章节（Entry point、Source-of-truth、提需求格式、BSP 边界、Runtime invariants、验收交付格式、构建命令），README 只保留给人看的项目介绍、硬件能力契约、demo 案例与项目结构；构建命令章节删除（与 `docs/development/build-and-test.md` 重复）。
- 新增 `docs/development/agent-guide.md`：集中承载"AI 如何在本仓库工作"（上下文建立顺序、事实来源优先级、提需求格式、BSP 边界、运行时规则、交付格式），并链接 build-and-test 与硬件指南，不重复构建命令与验收矩阵。
- 同步更新索引：`AGENTS.md` 规则索引新增 agent-guide 条目；`docs/INDEX.md` 与 `docs/development/README.md` 新增 agent-guide 索引行。
- 文档补充：`docs/fork-guide.md` 说明「为什么根目录不放置 README」——根目录 README 预留给 fork 开发者自行放置（上游留空），fork 后可将自己的内容写入根目录 `README.md` 介绍 fork 后的项目；GitHub 显示优先级（根 README > docs/README.md）契合该预留意图。
- 分支合并：创建 `main-update` 分支（基于与上游一致的 main），将 `feature/repo-structure`、`ci/build-firmware`、`ci/sync-main` 三个分支合并进来，统一 docs 结构（CI 文档归入 `docs/development/`，workflow 文件随 ci 分支引入 `.github/workflows/`）；解决 development/software-design README 的 add/add 冲突。
- 合并后审查修复：`docs/INDEX.md` 补充 CI 文档索引；`docs/fork-guide.md` 修正 workflow 引用为 `.github/workflows/sync-main.yml`；`docs/README` 双语项目结构块补充 `.github/workflows/` 与 CI 文档说明。
- ci 分支 CI 文档路径调整：`ci/build-firmware` 的 `docs/software-design/CI-build-and-release.md` 与 `ci/sync-main` 的 `docs/software-design/CI-sync-main.md` 均移入各分支的 `docs/development/`（CI 属工程规范）；`docs/software-design/README.md` 保留为软件设计索引；feature 分支的 software-design 索引同步更新引用。
- fork 补充文档目录迁移：`assets/docs/` 移至 `docs/assets/`（文档素材归入 docs/ 更合理），新增 `docs/assets/.gitkeep` 空目录占位；同步更新 AGENTS.md / INDEX / doc-conventions / fork-guide 的路径引用。
- 文档结构调整：根目录不再放 README——上游英文 README 移入 `docs/README.md`、中文移入 `docs/README.zh_CN.md`（GitHub 从 docs/ 识别主 README）；原 `docs/README.md` 根总索引更名为 `docs/INDEX.md`；同步更新 AGENTS.md / CONTRIBUTING / SUPPORT / fork-guide / doc-conventions 的路径引用。
- 初始化项目文档：新增 `AGENTS.md`、`CLAUDE.md` 和 `CHANGELOG.md`。
- 仓库结构规整：上游英文 `README.md` 更名为 `README.en_US.md`，保留 `README.zh_CN.md`。
- 新增目录骨架：`docs/`（software-design / hardware-design）、`assets/`（fonts / images / music，各含 `README.md`）、`skills/`。
- 将上游硬件开发指南归位到 `docs/hardware-design/AI_HARDWARE_DEVELOPMENT_GUIDE.md`。
- 文档规范：子目录 readme 统一为大写 `README.md`；补充 fork 用户约定（main 只动根 README）。
- 扩展 fork 用户约定：`main` 分支允许修改根目录 `README.md` 和 `assets/docs/`（README 不足以说明项目时存放补充文档与素材）。
- 新增 `assets/docs/` 目录约定：上游 main 只保留空目录 `.gitkeep`，内容文件仅存在于 fork；使用方法规范写入 AGENTS.md「给 fork 用户」约定。
- CI 文档迁移：`docs/software-design/CI.md` 从本分支移除，迁至 `ci/build-firmware` 分支并改名为 `docs/software-design/CI-build-and-release.md`。
- 补充 `main` 分支策略说明：解释 `main` 保持干净的两大原因（与上游同步无冲突 + 多小项目按分支整理）；例外——执意 main 开发需停用 CI 自动同步；提醒 fork 用户默认 action 关闭需手动启用（此条为整个 CI 的通用要求，统一写入 AGENTS.md）。
- 文档拆分：将 `AGENTS.md` 按主题拆为公共文档——新增 `docs/contribution/`（doc-conventions.md、commit-and-pr.md）与 `docs/development/`（build-and-test.md、coding-conventions.md），新增 `docs/fork-guide.md`；`AGENTS.md` 精简为简介 + 项目概述 + 必读文档索引。
- 同步更新索引：`docs/software-design/README.md`、`README.en_US.md` / `README.zh_CN.md` 的 `docs/` 目录说明。
- 参考 cindy 仓库文档组织完善索引：新增 `docs/README.md` 根总索引；AGENTS.md 规则索引按触发场景改写（附触发条件）；`docs/contribution/` 与 `docs/development/` 的 README 补充收录标准。
- 引入社区治理文档（参照 cindy 改写，放仓库根目录）：新增 `CONTRIBUTING.md` / `.zh_CN.md`（贡献指南，针对 ESP-IDF/AI agent/fork 场景改写）、`CODE_OF_CONDUCT.md` / `.zh_CN.md`（贡献者公约）、`SECURITY.md` / `.zh_CN.md`（安全报告流程）、`SUPPORT.md` / `.zh_CN.md`（支持渠道）；AGENTS.md 与 docs/README.md 同步引用。
