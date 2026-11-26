# codex-repair

Windows 版 Codex 故障诊断与修复技能。按“症状 → 证据 → 修复 → 验证”处理问题，附带只读日志分析、进程代理检查与代理重启脚本。

## 解决哪些问题

- 发消息后循环重连 `1/5…5/5`、WebSocket 超时、HTTP 回落。
- Windows 系统代理正常，但 Codex 实际进程未继承代理变量。
- MCP 启动失败、应用打不开、登录失败、429 限流。
- 状态数据库异常与第三方增强工具卸载残留。

## 安装

需要 Windows、Git；运行 Python 辅助脚本需要 Python 3。进程环境检查仅支持原生 x64 Windows 进程和 64 位 Python。重启助手使用 PowerShell。

```powershell
git clone https://github.com/XCBoi/codex-repair.git "$env:USERPROFILE\.codex\skills\codex-repair"
```

如果该目录已存在，先备份并比较内容，避免覆盖自己的修改。使用自定义 `CODEX_HOME` 时，将技能放在其 `skills\codex-repair` 目录。

重新打开 Codex 会话后，可以说：

> 用 codex-repair 检查发消息重连的问题，先取证再修复。

也可以直接读取 [SKILL.md](SKILL.md)，手动执行对应步骤。

## 文件

| 文件 | 用途 |
|---|---|
| [SKILL.md](SKILL.md) | 诊断入口、常见故障与验证标准 |
| [代理排障说明](references/websocket-proxy.md) | WebSocket 代理继承、重启与分层验证 |
| [diagnose_logs.py](scripts/diagnose_logs.py) | 只读分析 SQLite 日志 |
| [inspect_proxy_env.py](scripts/inspect_proxy_env.py) | 检查指定进程的四个代理变量 |
| [restart_with_proxy.ps1](scripts/restart_with_proxy.ps1) | 显式加载代理变量后预检、重启并记录结果 |

日志检查示例：

```powershell
python scripts/diagnose_logs.py --kw "retrying sampling request" --days 1 --limit 10
python scripts/inspect_proxy_env.py <主进程PID> <后端PID>
```

`<...>` 是需替换的占位符。代理重启助手的预检参数和独立运行方式见代理排障说明；不要直接把历史 PID 或安装路径用于当前机器。

## 如何确认修复成功

代理排障需要同时验证实际进程环境、WebSocket 握手和真实新消息。单独的 doctor 成功或 HTTP 能出字，都不能证明桌面 WebSocket 已恢复。

参考环境曾在桌面 26.1117.4957.0 / CLI 0.171.0-alpha.13 上复现变量未继承；修复后，在桌面 26.1120.6357.0 / CLI 0.171.0-alpha.13.2 上再次验证通过。版本信息是案例范围，不能替代当前环境测试。

修复前备份；仅重启明确属于目标 Codex 的进程；不读取或修改登录凭据。分享诊断输出前检查其中是否包含自己的路径、会话信息或其他敏感内容。使用本地代理时，代理软件及其端口需要保持可用。
