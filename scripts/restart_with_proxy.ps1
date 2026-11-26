<# Explicitly reload user proxy variables, validate, restart the selected desktop
   process tree, and save bounded verification. No registry/config changes here.
   -CheckOnly performs preflight without stopping or starting any process.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$AppPath,
    [Parameter(Mandatory)][string]$CodexPath,
    [Parameter(Mandatory)][string]$ReportDirectory,
    [string]$PythonPath = 'python.exe',
    [ValidateRange(0,120)][int]$DelaySeconds = 0,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$appExe = (Resolve-Path -LiteralPath $AppPath).Path
$cliExe = (Resolve-Path -LiteralPath $CodexPath).Path
if ([IO.Path]::GetFileName($appExe) -notin @('ChatGPT.exe','Codex.exe')) { throw 'Unexpected desktop executable' }
$null = New-Item -ItemType Directory -Path $ReportDirectory -Force
$reportDir = (Resolve-Path -LiteralPath $ReportDirectory).Path
$result = [ordered]@{ status='preflight'; started=(Get-Date).ToString('o'); app=$appExe; cli=$cliExe }
function Save-Result { $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $reportDir 'restart-result.json') -Encoding utf8 }
function Desktop-Processes {
    @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $appExe })
}
try {
    if ($DelaySeconds) { Start-Sleep -Seconds $DelaySeconds }
    foreach ($key in 'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY') {
        $value = [Environment]::GetEnvironmentVariable($key,'User')
        if ([string]::IsNullOrWhiteSpace($value)) { throw "User variable $key missing" }
        [Environment]::SetEnvironmentVariable($key,$value,'Process')
    }
    $proxyUri = [uri]$env:HTTPS_PROXY
    if ($proxyUri.Scheme -notin @('http','https')) { throw 'This helper requires an HTTP/HTTPS proxy' }
    $tcp = [Net.Sockets.TcpClient]::new()
    try {
        $task = $tcp.ConnectAsync($proxyUri.Host,$proxyUri.Port)
        if (-not $task.Wait(3000) -or -not $tcp.Connected) { throw 'Proxy port unavailable' }
    } finally { $tcp.Dispose() }
    $env:NO_COLOR = '1'
    $doctor = (& $cliExe doctor 2>&1 | Out-String)
    $doctor | Set-Content -LiteralPath (Join-Path $reportDir 'doctor-preflight.txt') -Encoding utf8
    if ($doctor -notmatch 'websocket\s+connected \(HTTP 101') { throw 'Preflight WebSocket failed; desktop was not stopped' }
    $result.preflight_websocket = 'HTTP 101'
    $result.original_pids = @(Desktop-Processes | ForEach-Object { $_.ProcessId })
    if ($CheckOnly) { $result.status='preflight_passed'; Save-Result; return }
    $result.status='restarting'; Save-Result
    # Capture descendants of this desktop only; unrelated CLI sessions are excluded.
    $all = @(Get-CimInstance Win32_Process)
    $ids = [Collections.Generic.HashSet[int]]::new()
    foreach ($p in (Desktop-Processes)) { $null = $ids.Add([int]$p.ProcessId) }
    do {
        $changed = $false
        foreach ($p in $all) {
            if ($ids.Contains([int]$p.ParentProcessId) -and $ids.Add([int]$p.ProcessId)) { $changed=$true }
        }
    } while ($changed)
    if ($ids.Contains($PID)) { throw 'Run restart helper independently (WMI), outside the desktop process tree' }
    foreach ($processId in $ids) { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue }
    $deadline = (Get-Date).AddSeconds(10)
    while ((Desktop-Processes).Count -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
    if ((Desktop-Processes).Count) { throw 'Old desktop remains; refusing duplicate launch' }
    $desktop = Start-Process -FilePath $appExe -PassThru
    $result.launch_pid = $desktop.Id
    $deadline = (Get-Date).AddSeconds(45)
    do {
        Start-Sleep -Seconds 2
        $current = @(Get-CimInstance Win32_Process)
        $apps = @($current | Where-Object { $_.ExecutablePath -eq $appExe })
        $appIds = @($apps | ForEach-Object { $_.ProcessId })
        $backends = @($current | Where-Object { $_.ExecutablePath -eq $cliExe -and $_.ParentProcessId -in $appIds })
    } while (($apps.Count -eq 0 -or $backends.Count -eq 0) -and (Get-Date) -lt $deadline)
    if (-not $apps.Count -or -not $backends.Count) { throw 'Desktop/backend did not appear within 45 seconds' }
    $probeIds = @($apps | Where-Object { $_.ParentProcessId -notin $appIds } | ForEach-Object { $_.ProcessId })
    $probeIds += @($backends | ForEach-Object { $_.ProcessId })
    $inspection = (& $PythonPath (Join-Path $PSScriptRoot 'inspect_proxy_env.py') @probeIds | Out-String)
    if ($LASTEXITCODE -ne 0) { throw 'Process environment inspection failed' }
    $inspection | Set-Content -LiteralPath (Join-Path $reportDir 'process-proxy-env.json') -Encoding utf8
    $entries = @($inspection | ConvertFrom-Json)
    foreach ($entry in $entries) {
        if ($entry.error) { throw "Environment inspection unknown for PID $($entry.pid)" }
        foreach ($key in 'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY') {
            if (-not $entry.matches_user_registry.$key) { throw "Proxy inheritance failed for PID $($entry.pid), $key" }
        }
    }
    $result.verified_pids = $probeIds
    $doctor = (& $cliExe doctor 2>&1 | Out-String)
    $doctor | Set-Content -LiteralPath (Join-Path $reportDir 'doctor-after-restart.txt') -Encoding utf8
    if ($doctor -notmatch 'websocket\s+connected \(HTTP 101') { throw 'Post-restart doctor WebSocket failed' }
    $result.status='process_environment_and_doctor_verified'
    $result.chat_verification='pending a real new message; doctor alone does not verify desktop sampling'
    Save-Result
} catch {
    $result.status='failed'; $result.error=$_.Exception.Message; Save-Result
    throw
}
