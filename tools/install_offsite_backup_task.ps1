param([string]$DailyAt = '06:45')
$ErrorActionPreference = 'Stop'
$backupJobScript = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'run_offsite_backup_job.py')).Path
$backupPythonPath = (& python -c 'import sys; print(sys.executable)').Trim()
$backupPythonwPath = Join-Path (Split-Path -Parent $backupPythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $backupPythonwPath -PathType Leaf)) { throw 'Python windowless runtime is missing' }
$backupTaskName = 'TIO-Offsite-Backup'
$backupIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$backupAction = New-ScheduledTaskAction -Execute $backupPythonwPath -Argument ('"{0}" --if-due --retention-days 31' -f $backupJobScript) -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$backupDailyTrigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
$backupLogonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $backupIdentity.Name
$backupLogonTrigger.Delay = 'PT2M'
$backupPrincipal = New-ScheduledTaskPrincipal -UserId $backupIdentity.User.Value -LogonType Interactive -RunLevel Limited
$backupTaskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1) -RestartInterval (New-TimeSpan -Minutes 15) -RestartCount 3
$backupExistingTask = Get-ScheduledTask -TaskName $backupTaskName -ErrorAction SilentlyContinue
if ($backupExistingTask -and $backupExistingTask.Description -ne 'TIO verified encrypted platform backup to this Windows profile') {
    throw 'Refusing to replace a task with an unrelated description'
}
Register-ScheduledTask -TaskName $backupTaskName -Description 'TIO verified encrypted platform backup to this Windows profile' -Action $backupAction -Trigger @($backupDailyTrigger,$backupLogonTrigger) -Principal $backupPrincipal -Settings $backupTaskSettings -Force | Out-Null
$backupInstalledTask = Get-ScheduledTask -TaskName $backupTaskName
[pscustomobject]@{
    task_name = $backupInstalledTask.TaskName
    state = [string]$backupInstalledTask.State
    daily_local_time = $DailyAt
    windows_time_zone = (Get-TimeZone).Id
    run_at_logon = $true
    interactive_current_user = $true
    stored_windows_password = $false
    start_when_available = $backupInstalledTask.Settings.StartWhenAvailable
    executable = $backupPythonwPath
    job_script = $backupJobScript
} | ConvertTo-Json
