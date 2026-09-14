[English](hooks.md) · [首页](../README.zh_CN.md)

# Codex hooks

本机和 SSH 主机使用相同的实时事件通道。各主机在 `~/.codex/hooks.json` 保存定义，共用原生发送器 `~/.codex/passport/hook`；`hook.py` 是常驻接收器。安装时两端需要 C 编译器 `cc`，安装器按各主机架构编译；运行接收器需要 Python 3。桥接从工作区启动本机接收器，通过 SSH 启动远端接收器，无需安装远端守护服务。

## 安装

```bash
python3 scripts/codex-hooks.py install --remote HOST_ALIAS --trust
python3 scripts/codex-hooks.py status --remote HOST_ALIAS
cargo build --release --manifest-path rust-bridge/Cargo.toml
./scripts/bridge-service.sh restart
```

将 HOST_ALIAS 替换为 `config/bridge.json` 中已配置的别名，多主机重复 `--remote`。安装器只合并 Passport 的处理器，修改前备份已有 hooks。`--trust` 使用 Codex 正常的 `hooks/list` 和 `config/batchWrite` 审阅流程启用这七个定义，事先备份 `config.toml`。Codex 会在 `hooks.state` 保存信任哈希，脚本定义仍在 hooks.json。现有 notify 和其他 hooks 保留。不加 `--trust` 时，通过 Codex `/hooks` 审阅启用后再使用。**安装完成不代表已有 Codex 会话已生效。** 安装器会通过已有远端 App Server 在线刷新会话，返回 `activation.state=reloaded` 才表示刷新成功；刷新依赖本工作区 `.venv` 中的 wsproto，不可用时明确返回 `restart_required`。本机桌面 Codex 没有可连接的刷新接口，安装器明确要求退出并重新打开 Codex。仅重启 Passport 不会刷新 Codex 的会话配置。

```bash
python3 scripts/codex-hooks.py uninstall --remote HOST_ALIAS
```

卸载只删除 Passport 处理器，保留脚本和私有备份供回退。远端自动刷新已有会话使卸载生效；本机需重启 Codex，否则旧会话仍可能运行已缓存的 hooks。若要停止该主机接收器，还应从桥接配置移除对应别名。status 检查安装状态；来源和设备运行状态用 `bridge-service.sh status` 查看。来源 healthy 仅证明接收器在线，不能证明已有 Codex 会话已加载 hooks；首次安装须以真实任务的开始和完成事件验证。

## 事件和生命周期

| Hook | 含义 |
| --- | --- |
| UserPromptSubmit | 开始／更新当前在线执行轮次，关闭之前的输入等待 |
| PermissionRequest | 授权等待提醒 |
| PreToolUse | 仅检测 request_user_input / request_user_input_async |
| PostToolUse | 结束同步等待；异步问题继续保留 |
| Stop | 观察活动会话文件，不直接判定完成 |
| Interrupt | 以中断状态结束轮次 |
| SessionEnd | 清理剩余在线状态 |

Codex 0.153.4 的 Stop 后可能继续执行，失败时可能没有 Stop。因此接收器仅监听新 hook 提供的会话文件，从事件记录的字节位置开始，通过 macOS kqueue／Linux inotify 读取追加内容。`task_complete` 判定成功／失败，`turn_aborted` 处理中断。不发现旧会话、不扫描历史、不在重连后补采。最终记录格式与版本有关，升级 Codex 后必须回归验证。Codex 突然崩溃且没有结束记录时不会推断成功；崩溃恢复不在此设计范围内。

Codex 的临时工作（例如自动生成任务标题）没有会话记录文件。接收器忽略这类工作的开始／等待 hook，避免残留虚假的运行中任务。只有成功打开并监听记录文件后，任务才会进入运行计数。


Hook 返回中性 `{}`，通过私有 Unix 流 socket 发送输入，IPC 超时 50 毫秒。原生发送器不启动 Python；已有 Python 接收器在内存中解析输入，不落盘，也不把提示词、工具输入或回答传到 SSH。跨主机只发送元数据。接收器注册会话文件监听后才确认接收，防止极短任务结束事件丢失。普通 PostToolUse 若无相关等待，会直接丢弃，不查标题、不计算授权摘要、不发送 Rust 事件；标题仅在开始、停止和进入等待等低频事件时查询。授权关联仍使用工具／输入摘要。仅跟踪根任务，忽略子代理 hook。接收器每五秒报告存活，区分空闲与故障。账号额度／token RPC 独立运行。

断线事件直接丢弃，接收器重启从空状态开始，设备重连不恢复旧通知。运行／等待状态保存在内存。已有桥接数据库仅服务当前在线投递事务和计数，不作为离线事件队列。设备已收到的通知由固件管理；OK 不会授权 Codex 请求。

## 验证

```bash
python3 scripts/codex-hooks/test_hooks.py
python3 scripts/codex-hooks/test_codex_runtime.py
python3 scripts/codex-hooks/benchmark.py --count 60 --title-hit --max-cpu-ms 15
cargo test --manifest-path rust-bridge/Cargo.toml
cargo clippy --manifest-path rust-bridge/Cargo.toml -- -D warnings
```

运行时测试在临时 CODEX_HOME 中启动实际安装的 Codex，对接回环模拟模型，覆盖临时标题任务、成功、失败、Stop 后继续、同步／异步输入、授权、中断，以及已有会话在安装／卸载后的配置刷新，不请求真实模型或账号。Linux 上用 CODEX_BIN 指定可执行文件。这些属于主机测试，不是设备测试；真实硬件需另外检查来源状态和通知接收。

如需将运行时测试明确送入真实硬件，把 `PASSPORT_TEST_LIVE_SOCKET` 设为正在运行的本机接收器 `events.sock` 绝对路径，会产生实际通知和声音。在 SSH 主机上使用相同选项可验证远端到设备的链路。

性能基准仅使用隔离接收器和合成工具输入，包含实际 Shell 和原生发送器的启动成本，单核 CPU 百分比按每秒一次回调估算。不会向设备发送测试通知。

## 额度快照

启动时读取额度，此后每五分钟固定校准；任务事件不会推迟校准。receiver 仅从已监听任务记录的新增内容提取新鲜的 token_count.rate_limits 窗口，不扫描历史、不新增模型或账号请求。只有配置的 account_host 在账号身份校验有效时才能更新 codex 类别；其他主机、类别、异常快照和旧时间戳均忽略。每分钟通过本地 account/read RPC 核对身份，这不是云端额度查询。

任务快照保留重置卡和 token 用量字段。即使快照继续到达，连续 15 分钟校准未成功也会隐藏过期卡信息。额度在 10 分钟内视为新鲜；请求失败保留最后已知值及更新时间，不影响 hook 链路健康状态。不离线重放。主机不产出额度事件时，五分钟校准仍有效。

桥接允许来源时钟最多快五秒，并将接受的时间戳限制在本机接收时间以内；更大的时钟误差会被拒绝。这样 Mac/Linux 的小幅时钟差不会悄悄丢弃实时快照，也不会产生未来的新鲜度时间戳。
