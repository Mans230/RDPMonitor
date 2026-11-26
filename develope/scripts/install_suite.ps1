param([switch]$Remove, [string]$Python)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

function Resolve-Python {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $real = & $py.Source -3 -c "import sys; print(sys.executable)" 2>$null
        if ($real -and (Test-Path $real)) { return $real }
    }
    throw 'Python 3 was not found. Install Python or run: python rdp_suite.py install'
}


function Remove-SuiteTasks {
    foreach ($name in @('RDPSuite', 'RDPSuiteBackup')) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task) {
            Stop-ScheduledTask -InputObject $task -ErrorAction Stop
            Unregister-ScheduledTask -InputObject $task -Confirm:$false -ErrorAction Stop
        }
    }
}

function Remove-LegacyTasks {
    foreach ($name in @('rdp', 'RDPMonitor', 'RDPWebConsole', 'VPSBackupTool')) {
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    }
}


$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this installer from an Administrator terminal.'
}

if ($Remove) {
    Remove-SuiteTasks
    Write-Output 'RDP Suite scheduled tasks removed. Configuration and data were preserved.'
    exit 0
}

if (-not $Python) { $Python = Resolve-Python }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Python executable not found.' }
$Pythonw = Join-Path (Split-Path -Parent $Python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $Pythonw)) { $Pythonw = $Python }
$Account = $identity.Name

Remove-SuiteTasks
Remove-LegacyTasks

$userAction = New-ScheduledTaskAction -Execute $Pythonw `
    -Argument ('"' + (Join-Path $Root 'rdp_suite.py') + '" --user-runtime') -WorkingDirectory $Root
$userTrigger = New-ScheduledTaskTrigger -AtLogOn -User $Account
$userPrincipal = New-ScheduledTaskPrincipal -UserId $Account -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'RDPSuite' -Action $userAction -Trigger $userTrigger `
    -Principal $userPrincipal -Settings $settings `
    -Description 'RDP Suite - monitor and hardened local WebConsole' -Force | Out-Null

$backupMain = Join-Path $Root 'backup\app\main.py'
$backupAction = New-ScheduledTaskAction -Execute $Pythonw -Argument ('"' + $backupMain + '" --daemon') `
    -WorkingDirectory (Join-Path $Root 'backup\app')
$boot = New-ScheduledTaskTrigger -AtStartup
$boot.Delay = 'PT1M'
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(-5) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$system = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'RDPSuiteBackup' -Action $backupAction -Trigger $boot,$repeat `
    -Principal $system -Settings $settings `
    -Description 'RDP Suite - scheduled backup and backup Telegram bot' -Force | Out-Null

# A start failure must not invalidate a successful registration (for example
# the interactive trigger cannot start when no matching session exists yet).
try { Start-ScheduledTask -TaskName 'RDPSuite' -ErrorAction Stop }
catch { Write-Output ('Registered RDPSuite, but it could not start now: ' + $_.Exception.Message) }
try { Start-ScheduledTask -TaskName 'RDPSuiteBackup' -ErrorAction Stop }
catch { Write-Output ('Registered RDPSuiteBackup, but it could not start now: ' + $_.Exception.Message) }
Write-Output 'RDP Suite installed: one user runtime and one isolated SYSTEM backup worker.'
