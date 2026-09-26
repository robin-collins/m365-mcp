<#
.SYNOPSIS
    Register a weekly Windows Task Scheduler job that refreshes a personal
    account's token, so the refresh token never expires from disuse (R1).

.DESCRIPTION
    Runs `uv run authenticate.py --re-auth <Account>` from the repository
    root every week. The script exits with code 1 when interactive sign-in
    is required; Task Scheduler then shows "Last Run Result: 0x1".
    Nothing is created unless you run this script; use -WhatIf to preview.

.EXAMPLE
    .\scripts\register_reauth_task.ps1 -Account you@outlook.com -WhatIf
    .\scripts\register_reauth_task.ps1 -Account you@outlook.com
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$Account,
    [string]$TaskName = "M365-MCP-ReAuth",
    [ValidateSet("Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday")]
    [string]$DayOfWeek = "Sunday",
    [string]$At = "09:00"
)

$repo = Split-Path -Parent $PSScriptRoot
$uv = (Get-Command uv -ErrorAction Stop).Source
$action = New-ScheduledTaskAction -Execute $uv `
    -Argument "run authenticate.py --re-auth $Account" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun:$false

if ($PSCmdlet.ShouldProcess($TaskName, "Register weekly re-auth task for $Account")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Description "Refresh the M365 MCP token for $Account" | Out-Null
    Write-Host "Registered '$TaskName'. Run it once now with: Start-ScheduledTask -TaskName $TaskName"
    Write-Host "Then check: (Get-ScheduledTaskInfo -TaskName $TaskName).LastTaskResult  (0 = refreshed, 1 = sign in again)"
}
