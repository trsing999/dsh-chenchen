param([switch]$DryRun)

# stop every chen-chen background service, leave DeepSeek Harness itself alone
# 用脚本自己的位置推导插件根：装到 node_modules 里也能找到 logs。
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$logdir = Join-Path $root 'logs'
$log = Join-Path $logdir 'kill_switch.log'
$count = Join-Path $logdir 'kill_switch.count'

# any python script launched from the tools folder is "hers" -> stop it
$pattern = 'tools\\[^\\]+\.py'

$killed = @()
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.ProcessId -ne $PID } |
    Where-Object { $_.CommandLine -match $pattern } |
    Where-Object { $_.CommandLine -notmatch 'kill_switch' } |
    ForEach-Object {
        $killed += ('{0} {1}' -f $_.ProcessId, $_.CommandLine)
        if (-not $DryRun) {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }

if ($DryRun) {
    $killed | ForEach-Object { $_ }
    ('DRY RUN: {0} would be stopped' -f $killed.Count)
    exit 0
}

New-Item -ItemType Directory -Force -Path $logdir | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
("[{0}] killed {1}" -f $stamp, $killed.Count) | Out-File -FilePath $log -Append -Encoding utf8
if ($killed.Count -gt 0) {
    $killed | Out-File -FilePath $log -Append -Encoding utf8
}
$killed.Count | Out-File -FilePath $count -Encoding ascii
$killed.Count
