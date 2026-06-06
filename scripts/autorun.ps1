# autorun.ps1 — Full job-hunt pipeline: search → score → packet → auto-apply
#
# Usage:
#   .\scripts\autorun.ps1
#   .\scripts\autorun.ps1 -MinScore 75 -Limit 5 -Mode full_auto
#
# Scheduled Task registration (runs every 2 hours):
#   .\scripts\autorun.ps1 -Register -IntervalHours 2
#
# Requirements:
#   - .venv in the project root with all dependencies installed
#   - ANTHROPIC_API_KEY set as a machine/user environment variable
#   - Chrome installed and logged into relevant job sites

param(
    [float]$MinScore = 70,
    [int]$Limit = 10,
    [string]$Mode = "fill_and_confirm",
    [switch]$Register,
    [int]$IntervalHours = 2
)

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
$Venv = Join-Path $Root ".venv\Scripts"
$Python = Join-Path $Venv "python.exe"
$Script = Join-Path $Root "scripts\auto_apply.py"

if ($Register) {
    $Action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NonInteractive -File `"$($MyInvocation.MyCommand.Definition)`" -MinScore $MinScore -Limit $Limit -Mode $Mode" `
        -WorkingDirectory $Root
    $Trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours $IntervalHours) -Once -At (Get-Date)
    $Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
    Register-ScheduledTask `
        -TaskName "JobAgent-AutoApply" `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Description "Free Job Agent — automated apply session every $IntervalHours hour(s)" `
        -Force
    Write-Host "Scheduled task 'JobAgent-AutoApply' registered (every $IntervalHours hour(s))."
    exit 0
}

if (-not (Test-Path $Python)) {
    Write-Error "Python venv not found at $Venv. Run: python -m venv .venv && .venv\Scripts\pip install -e ."
    exit 1
}

Write-Host "=== Free Job Agent — Auto-Run ===" -ForegroundColor Cyan
Write-Host "Root   : $Root"
Write-Host "Mode   : $Mode"
Write-Host "Score  : >= $MinScore"
Write-Host "Limit  : $Limit"
Write-Host ""

# Activate venv (sets PATH so pip/python resolve correctly)
& (Join-Path $Venv "Activate.ps1")

# Start the dashboard server in the background (if not already running)
$serverRunning = Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue
if (-not $serverRunning) {
    Write-Host "Starting dashboard server in background…"
    $serverProcess = Start-Process `
        -FilePath $Python `
        -ArgumentList (Join-Path $Root "src\job_agent\ui\server.py") `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Seconds 3
} else {
    Write-Host "Dashboard server already running on port 8765."
    $serverProcess = $null
}

# Run the auto-apply session
Write-Host "Running auto-apply…"
& $Python $Script --mode $Mode --min-score $MinScore --limit $Limit
$exitCode = $LASTEXITCODE

# Tear down server if we started it
if ($serverProcess -and -not $serverProcess.HasExited) {
    Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
}

exit $exitCode
