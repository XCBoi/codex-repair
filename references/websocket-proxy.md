# Windows WebSocket 代理与进程继承

用于“每次发送先重连 1/5…5/5，随后 HTTP 才出字”。不要推广到所有版本或所有网络故障。

## 证据

本机 2026-11-24 的复核：直连 chatgpt.com 在 12 秒测试上限内超时；显式走 `http://127.0.0.1:7890` 返回 HTTP 200，约 1.8 秒。未带代理变量的 CLI doctor WebSocket 超时；显式加载后返回 HTTP 101。

此前的误判是把“注册表写入成功 + 另起的 doctor 成功”当作“桌面已修复”。实际桌面主进程和后端没有继承变量，真实消息仍重试回落。已有父进程不会因写注册表自动更新环境。

### 修复后与版本更新后的复验

| 检查 | 2026-11-24 修复后 | 2026-11-26 14:22（北京时间）更新后 |
|---|---|---|
| 桌面 / CLI 版本 | 26.1117.4957.0 / 0.171.0-alpha.13 | 26.1120.6357.0 / 0.171.0-alpha.13.2 |
| 实际进程环境 | 新主进程和两个后端四键匹配用户注册表 | 新主进程和两个后端四键仍匹配 |
| doctor 握手 | HTTP 101 | HTTP 101 |
| 桌面实际握手 | HTTP 101 | HTTP 101 |
| 真实新消息 | WebSocket 请求，重试 0 / HTTP 回落 0 | WebSocket 请求 3 条记录，重试 0 / HTTP 回落 0 / WebSocket 连接错误 0 |

11 月 26 日显式代理 HTTP 测试返回 200，耗时 2.165 秒；实际消息按当前 turn 的增量日志检查。三条请求记录来自同一 turn 的多次模型采样，不代表三条独立用户消息。复验期间没有再次修改配置或重启应用；结果支持已有修复在这次更新后仍生效，不能推出所有后续版本都已修复代理发现机制。

更新后后端路径已从用户目录的 `bin\<hash>\codex.exe` 变为当前安装包的 `app\resources\codex.exe`。每次复验应重新从运行进程发现路径和版本；不同版本的后端路径可能变化。

## 修复步骤

1. 发现实际桌面和后端路径，读取系统代理、用户注册表变量、当前 shell 变量，确认代理软件的监听端口。不要输出完整环境或认证文件。
2. 用有时限的 curl 比较直连与显式代理。TCP 超时仅证明该测试的直连失败，不足以锁定 ISP/DNS。
3. 若需要改用户变量，先保存这四个键的旧值；仅在已证实的代理地址上设置 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`，`NO_PROXY` 保留必要本地排除项。旧值为空和原本不存在应区分。回滚应恢复旧值，不能一律删除四键。
4. 在启动进程中显式读取用户变量。写注册表后可广播 `WM_SETTINGCHANGE` / `Environment` 让 Explorer 刷新；广播不证明已有应用更新，必须检查新进程。普通快捷方式仍不继承时，从明确加载变量的启动器运行，或在合适时间注销重登。
5. `python scripts/inspect_proxy_env.py <主PID> <后端PID>` 检查实际环境。助手仅读四个键，凭据型代理 URL 会遮盖；仅支持原生 x64，偏移读取失败是“未知”，不能记为“变量不存在”。
6. doctor 明确报错为未识别的 `respect_system_proxy` / `system_proxy_fallback` 可在备份后移除。不要把桌面 UI 的同名 session flag 推断成 CLI TOML 键。

## 可复用启动助手

参数路径应从本次发现结果填入，不要硬编码历史版本或 PID：

```powershell
& '<skill>\scripts\restart_with_proxy.ps1' `
  -AppPath '<实际桌面exe>' -CodexPath '<实际后端exe>' `
  -ReportDirectory '<本次报告目录>' -PythonPath '<64位python.exe>' -CheckOnly
```

预检仅在该助手进程内加载变量并检查代理端口和 doctor，不停止应用。实际重启去掉 `-CheckOnly`。脚本仅停止指定桌面路径及其后代，保留其他 CLI 会话；新启动进程显式继承助手环境。脚本不修改注册表、配置或登录文件。

**如果修复的是当前聊天宿主**，助手必须在宿主进程树之外运行，防止一起终止。可用 Windows WMI 的 `Win32_Process.Create` 启动隐藏 PowerShell：

```powershell
# 先检查完整命令中的路径，参数逐项加双引号，不能包含双引号本身。
# -WindowStyle Hidden 避免弹出后台控制台；延迟给当前回复留出保存时间。
$commandLine = '"<pwsh.exe>" -NoProfile -WindowStyle Hidden -File "<助手.ps1>" -AppPath "<桌面exe>" -CodexPath "<后端exe>" -ReportDirectory "<报告目录>" -PythonPath "<python.exe>" -DelaySeconds 30'
$launch = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=$commandLine}
if ($launch.ReturnValue -ne 0) { throw "Independent helper launch failed: $($launch.ReturnValue)" }
```

助手创建成功只表示已安排，不代表已重启或修复。重启会中断聊天连接；先保存技能、脚本和检查结果，再启动助手，不要承诺当前回复之后仍能自动继续同一 turn。

## 分层验证与停止条件

- `restart-result.json`：`preflight_passed` 仅为预检通过；`process_environment_and_doctor_verified` 表示实际主/后端环境匹配且 CLI 握手通过；`failed` 查具体 error。出现失败即停止，不循环强杀重启。
- `process-proxy-env.json`：检查 PID 是新进程，四键都与用户配置匹配。
- `doctor-after-restart.txt`：HTTP 101 是握手成功，不是“无代理直连成功”。doctor 对桌面是否在运行的自动识别在本机有误，不覆盖 CIM 的实际进程证据。
- 最后发送真实新消息，按会话/turn 与时间筛选增量日志，看 `retrying sampling request`、`falling back to HTTP`、WebSocket 错误。没有新消息时标注“消息级验证待完成”，不要用静默期间无错误代替。
- 对真实消息同时确认正向证据（该 turn 的 `responses_websocket.stream_request` 等请求记录）和反向证据（重试、回落、连接错误计数为 0）。只筛选这次 turn，历史错误不计入；记录采样截止时间/日志 ID，避免把当前观察结果描述成长期稳定性保证。

代理关闭或端口变化后连接可能失败；应说明此依赖。不要将未验证的第三方视觉排障命令作为该流程的一部分。
