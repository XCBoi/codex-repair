---
name: codex-repair
description: 诊断并修复 Windows 版 OpenAI Codex（桌面应用 / CLI）的常见故障：MCP 服务器启动失败、对话卡住超时、429 限流、状态库损坏、应用打不开、第三方增强工具（Codex++ 等）卸载残留。基于真实修复案例沉淀，按「症状→根因→证据→修复→验证」流程执行，可不断追加新条目。
---

# Codex 修复（Windows）

> 本 skill 由 Windows 环境下的实际排障案例整理：曾观察到 Codex 开新会话报
> `codex_plus_collaboration` MCP 启动失败、对话经常卡住重试 5 次 timeout、偶发 429、
> `memories_1.sqlite` 损坏。下面是完整可复用的诊断与修复流程。
> **本 skill 是"活文档"：遇到新问题请按文末《追加新条目》把新案例补进对照表。**

## 0. 关键路径速查（Windows）

| 对象 | 路径 |
|---|---|
| CODEX_HOME | `C:\Users\<user>\.codex` |
| 主配置 | `%CODEX_HOME%\config.toml`（UTF-8，可能含中文项目路径） |
| 认证 | `%CODEX_HOME%\auth.json`（**永远不要动**） |
| 日志库 | `%CODEX_HOME%\logs_2.sqlite`（表 `logs`：id, ts, level, target, feedback_log_body） |
| 状态库 | `state_5.sqlite`、`memories_1.sqlite`、`goals_1.sqlite`、`queue_1.sqlite`、`thread_history_1.sqlite` |
| 会话记录 | `%CODEX_HOME%\sessions\YYYY\MM\DD\rollout-*.jsonl(.zst)` |
| MSIX 安装目录 | `C:\Program Files\WindowsApps\OpenAI.Codex_<版本>_x64__2p2nqsd0c76g0\app` |
| CLI 二进制 | 优先从运行中的 `codex.exe` 的 `ExecutablePath` 发现，可能位于 `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`；旧版在 `<app>\resources\codex.exe` |
| 捆绑 rg | `<app>\resources\rg.exe` |
| Codex++ 残留 | `<旧 Codex++ 安装目录>`、`%CODEX_HOME%\.codex-plus-agent-mcp*`、`%CODEX_HOME%\.codex-session-delete`（Codex++ 状态目录） |
| 本机应用进程 | `Get-Process ChatGPT`（主窗口进程 `MainWindowTitle -eq ChatGPT`） |

## 1. 诊断流程（按顺序，先取证再动手）

1. **先跑 doctor**（只代表本次 CLI 调用环境，不代表桌面进程环境）：
   ```powershell
   # 先按父子关系定位目标桌面的后端；存在多个安装时不能任取第一个。
   $codex = '<该目标后端实际路径>'
   # 没有运行中的后端时，用 Get-Command codex 或安装目录发现实际二进制。
   $env:NO_COLOR='1'
   & $codex doctor
   ```
   重点看：`✗ state`（数据库损坏）、`⚠ mcp`（MCP 配置问题）、`⚠ websocket`、
   `✗ reachability`、`config.toml parse`。doctor 报告自带修复建议，先读它。

2. **读 config.toml**：用 read 工具，确认 `[mcp_servers.*]` 的 `command`/`args` 指向的
   程序是否真实存在。常见病：第三方工具被卸载后，MCP 配置还指向已删除的 exe。

3. **列 MCP 与特性开关**：
   ```powershell
   & $codex mcp list      # 看每个 server 的 Command/Status
   & $codex features list # 看响应式 WebSocket 等特性是否可关
   ```

4. **查日志库**（只读，用 python；不要用 sqlite3.exe——本机常缺）：
   见 `scripts/diagnose_logs.py`。关键检索词：
   `MCP server startup failed`、`request timed out`、`falling back to HTTP`、
   `429`、`Unauthorized`、`Request completed ... status=4xx/5xx`、`integrity`。

5. **网络检查**（WebSocket/卡顿类问题必查）：
   ```powershell
   # TCP 可达性
   Test-NetConnection chatgpt.com -Port 443 -InformationLevel Quiet
   # 系统代理是否指向已失效的本地端口（常见：FlClash/Clash 没开但代理还开着）
   Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' `
     -Name ProxyEnable,ProxyServer
   Get-NetTCPConnection -State Listen | ? { $_.LocalPort -in 7890,7891,7897,10808,10809 }
   # 常见代理进程
   Get-Process | ? { $_.ProcessName -match 'clash|v2ray|xray|sing-box|verge|mihomo' }
   ```

6. **进程/端口**：`Get-Process ChatGPT`；监听端口 `Get-NetTCPConnection -State Listen`。

> **经验**：能出字可能只是 HTTP 回落，不能证明 WebSocket 已修复。网络、环境变量继承和配置均需按证据区分；详见 §2.8。

## 2. 症状 → 根因 → 修复 对照表

### 2.1 MCP 服务器启动失败（最典型）
- **症状**：开新会话/新线程报错；日志：`MCP server startup failed server_name="xxx" error=系统找不到指定的路径。 (os error 3)`；doctor：`⚠ mcp ... command "..." is not resolvable`。
- **根因**：`config.toml` 的 `[mcp_servers.xxx]` 指向已删除的程序（常是第三方增强工具，如 Codex++ 的 `<旧安装目录>\codex-plus-plus.exe`）。
- **修复**（先备份，再删除，不要手改文件）：
  ```powershell
  Copy-Item "$env:USERPROFILE\.codex\config.toml" "$env:USERPROFILE\.codex\config.toml.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
  & $codex mcp remove <server_name>   # 例如 codex_plus_collaboration
  ```
- **验证**：`codex mcp list` 里该 server 消失；重启应用后新日志无 `MCP server startup failed`。

### 2.2 对话卡住 / 转圈 / 重试 5 次 timeout
- **症状**：发消息后长时间无输出；日志：`stream disconnected - retrying sampling request (5/5)... sampling_error=request timed out`、`falling back to HTTP`；doctor：`⚠ websocket Responses WebSocket timed out`。
- **根因**：`wss://chatgpt.com/backend-api/...` WebSocket 握手/流中断（代理失效、DNS、防火墙、ISP 对 chatgpt.com 的 TCP 阻断），客户端重试 5 次后回落 HTTP。
- **修复**：这是网络问题，按诊断流程第 5 步排查：
  - 若系统代理指向 `127.0.0.1:7890` 等但代理软件没运行 → 启动代理（如 FlClash）或关掉失效代理（`Win+R → inetcpl.cpl → 连接 → 局域网设置`）。
  - 若直连失败而显式代理成功，按 §2.8 排查；不能仅凭 TCP 超时认定 ISP 阻断或建议换 DNS。
  - **注意**：本机 0.171.0-alpha.13 的 `features list` 中 `responses_websockets` / `responses_websockets_v2` 是 `removed`，不要用这些开关关闭 WebSocket；其他版本先查实际输出。能出字只能证明存在可用传输。
- **验证**：发一条消息能正常流式输出；日志无连续 `retrying sampling request`。

### 2.3 429 / 额度 / 限流
- **症状**：请求返回 429，日志出现限流或额度相关提示。
- **取证**：读取响应正文、重试时间和账号界面提示；区分额度耗尽、短时速率限制、网关或上游返回的 429，不能只凭状态码确定原因。
- **处理**：以实际账号套餐和服务提示为准；按提示等待或降低并发。不要承诺固定的重置窗口，也不要声称存在通用的手动 Reset 功能。
- **验证**：新请求恢复，且同一请求对应的日志不再出现该错误。

### 2.4 状态库损坏
- **症状**：doctor 报数据库 integrity check 失败、unable to open database file，或相关状态功能异常。
- **取证**：确认具体文件、权限、磁盘空间和只读完整性检查结果；不要把“打不开”一律当作损坏。
- **修复**：仅在已确认损坏、备份完成且相关进程完全退出后，隔离具体数据库及必要的 WAL/SHM 配套文件。数据库可能包含历史或记忆，不能假设所有文件都能自动重建。先确认该版本的恢复机制；不要删除全部状态库或操作正在写入的数据库。
- **验证**：恢复后检查完整性及对应功能；报告任何数据恢复限制。

### 2.5 应用打不开 / 白屏 / 登录失败
- **取证**：检查目标 Codex 的实际安装路径、进程树、启动日志与 doctor。不要仅凭同名 ChatGPT.exe 判定进程归属。
- **修复**：如需重启，仅停止已确认属于目标 Codex 的进程树，再从实际安装路径启动；代理环境继承问题按 §2.8 处理。
- **登录失败**：结合认证端点响应和登录界面判断；必要时让用户通过官方界面重新登录，不打印或修改 auth.json。
- **验证**：主窗口正常、实际新消息成功，并核对对应日志。

### 2.6 第三方增强工具（Codex++）卸载残留
- **症状**：`MCP server startup failed`（见 2.1）；`~/.codex` 出现 `.codex-plus-agent-mcp-*` 文件；`~/.codex-session-delete` 目录（Codex++ 状态目录）。
- **修复**：归档而非删除：
  ```powershell
  $q="$env:USERPROFILE\.codex\codexplus-leftovers-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
  New-Item -ItemType Directory $q | Out-Null
  foreach($n in '.codex-plus-agent-mcp.lock','.codex-plus-agent-mcp-backups',
                 'codex-plus-gateway-connection-generation','codex-plus-gateway-connection-generation.lock'){
    $p="$env:USERPROFILE\.codex\$n"; if(Test-Path $p){ Move-Item $p $q } }
  ```
  然后按 2.1 移除 MCP 配置。若想恢复 Codex++，安装包常在 `~\.codex-session-delete\updates\CodexPlusPlus-<版本>-windows-x64-setup.exe`。

### 2.7 doctor 杂项警告（按影响判断）
- `⚠ search ... cannot find binary path`（rg）：检查实际二进制和 PATH；是否影响搜索以实际调用为准。
- `⚠ threads ... rollout files missing`：检查缺失文件是否影响目标历史会话，勿直接删除状态库。
- `⚠ updates ... version cache missing`：更新检查失败，通常是网络，不影响使用。

### 2.8 每次发任务重连：WebSocket 代理环境未继承

- **已复现版本**：Windows 桌面 26.1117.4957.0，CLI 0.171.0-alpha.13。系统代理开启时，HTTP 可达，未带代理变量的 WebSocket 握手仍超时；仅对已测版本/环境作此结论。
- **修复后复验通过**（2026-11-26）：更新至桌面 26.1120.6357.0 / CLI 0.171.0-alpha.13.2 后，主进程与两个后端仍正确继承四个代理变量；doctor 和桌面实际握手均为 HTTP 101；真实新消息有 WebSocket 请求，重试、HTTP 回落及连接错误均为 0。该结果验证此环境下修复在本次更新后仍生效，不代表新版本无需代理变量；详细证据见引用文档。
- **决定性反例**（2026-11-24）：用户注册表有四个代理变量，但实际桌面主进程及两个后端的环境均为空；新消息仍重试 5/5 后回落 HTTP。显式加载变量的 doctor 返回 HTTP 101，不能据此宣称桌面修复成功。
- **取证与修复**：见 [references/websocket-proxy.md](references/websocket-proxy.md)。区分注册表、当前 shell、桌面主进程和后端四层环境；从明确加载变量的独立进程重启目标桌面进程树。
- **验证标准**：实际新主进程与后端的四个变量匹配用户配置；同环境 doctor HTTP 101；最后用真实新消息和对应增量日志确认没有重连与 HTTP 回落。最后一项未测时明确标为待验证。
- **更新后复验**：重新发现当前 PID、桌面版本和后端二进制路径，再执行上述验证；不要沿用历史 PID、旧 CLI 的 doctor 或旧日志。确认该消息确实产生 WebSocket 请求后，才能将该 turn 的“0 次重试/回落”记为通过。
- `respect_system_proxy` / `system_proxy_fallback` 在本机被 doctor 明确报为未识别并忽略；不能当作有效 TOML 代理设置。备份后可移除这些已确认忽略的键。

## 3. 通用安全规则（每次修复必须遵守）

1. **改任何配置前先备份**：`config.toml` → `config.toml.bak-<时间戳>`。
2. **用官方命令而不是手改文件**：MCP 用 `codex mcp remove/add`；特性用 `codex features`。
3. **隔离（Move-Item）而不是删除** 损坏文件/残留，便于回滚取证。
4. **需要进程重新加载的改动才重启**。只操作已确认属于目标 Codex 的进程树，避免按同名进程全杀。代理环境修改见 §2.8；从旧环境直接重开可能再次失败。修复当前聊天宿主时先保存工作，用独立隐藏助手重启并落盘验证；重启安排成功不等于验证通过。
5. **永远不动 `auth.json`**；不动 `app.asar`、`.agent-teams` 等源码/状态文件。
6. **验证三件套**：`codex doctor` 相关行变绿 + `codex mcp list` 正确 + 重启后新日志无 ERROR/对应关键词。
7. 应用运行时会**重写 config.toml**（如 `conversationDetailMode`、`startup_timeout_sec` 数值化），这是正常行为；重写后保持 UTF-8 与有效 TOML 即可。

## 4. 日志库查询（logs_2.sqlite）

- 表：`logs(id, ts, level, target, feedback_log_body, ...)`；`ts` 是 Unix 秒。
- 常用 SQL：
  - 最近错误：`select id,ts,level,target,substr(feedback_log_body,1,400) from logs where level in ('ERROR','WARN') order by id desc limit 40`
  - 按天统计关键词：`select date(ts,'unixepoch','localtime'), count(*) from logs where feedback_log_body like '%关键词%' group by 1 order by 1 desc`
  - 采样错误：`... where feedback_log_body like '%sampling_error=%'`
  - 请求状态：`... where feedback_log_body like '%Request completed%'`
- 完整脚本见 `scripts/diagnose_logs.py`（只读打开，可传关键词参数）。

## 5. 验证清单（修复收尾）

- [ ] `codex doctor`：config parse ok、MCP servers 数量正确、state 绿、auth ✓
- [ ] `codex mcp list`：无失效 server
- [ ] 重启后新日志（按 max(id) 增量）：无对应故障的新错误；无关历史错误另行判断
- [ ] 应用主窗口正常，真实消息成功；WebSocket 握手用 HTTP 101、HTTP 请求用实际预期状态验证
- [ ] 备份文件存在（config.toml.bak-*、*.broken-*、leftovers-*）
- [ ] 代理修复：核对实际桌面/后端环境；doctor 和真实新消息分别验证，不能用前者替代后者

## 6. 追加新条目（让 skill 持续生长）

遇到**新的** Codex 问题时：
1. 先按第 1 节诊断取证，找到「症状 → 根因 → 证据（日志/doctor 原文）→ 修复 → 验证」五要素。
2. 把新案例追加到第 2 节对照表（保持同样的编号格式）。
3. 如发现新的日志关键词或路径，同步更新第 0/4 节。
4. 若修复流程复杂，可新增 `references/<案例名>.md` 存详细过程，SKILL.md 里留一行索引。

## 7. 脚本

- `scripts/diagnose_logs.py` — 只读分析 Codex 日志库，输出最近 ERROR/WARN、按天统计、关键词命中。用法见脚本头注释。
- `scripts/inspect_proxy_env.py PID [PID ...]` — 只读检查 x64 Windows 进程的四个代理变量并与用户注册表比对；不输出完整环境，读取失败表示未知。
- `scripts/restart_with_proxy.ps1` — 显式加载用户代理变量，先验证 HTTP 101，再重启指定桌面进程树，记录新进程环境与 doctor。先用 `-CheckOnly` 做预检；参数与独立运行方式见 §2.8 引用。
