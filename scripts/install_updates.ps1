param([switch]$Remove, [string]$Python)
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
if ($Remove) {
    $Task=Get-ScheduledTask -TaskName RDPSuiteUpdate -ErrorAction SilentlyContinue
    if ($Task) { Stop-ScheduledTask -InputObject $Task; Unregister-ScheduledTask -InputObject $Task -Confirm:$false }
    exit 0
}
$Identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$Principal=New-Object Security.Principal.WindowsPrincipal($Identity)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator access is required.' }
if (-not $Python) { $Python=(Get-Command python.exe -ErrorAction Stop).Source }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Python executable not found.' }
& $Python (Join-Path $Root 'suite_update.py') init
if ($LASTEXITCODE -ne 0) { throw 'Cannot initialize protected updater storage.' }
$Pythonw=Join-Path (Split-Path -Parent $Python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $Pythonw)) { $Pythonw=$Python }
$Action=New-ScheduledTaskAction -Execute $Pythonw -Argument ('"'+(Join-Path $Root 'suite_update.py')+'" --scheduled') -WorkingDirectory $Root
$Boot=New-ScheduledTaskTrigger -AtStartup
$Boot.Delay='PT2M'
$Hourly=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$System=New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Highest
$Settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName RDPSuiteUpdate -Action $Action -Trigger $Boot,$Hourly -Principal $System -Settings $Settings -Description 'Validated bot and panel updates; code rollback on failed health checks' -Force | Out-Null
Write-Output 'Suite updater installed. Automatic installation remains controlled by its saved settings.'
