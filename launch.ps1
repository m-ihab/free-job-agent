param(
  [int]$Port = 8765,
  [switch]$NoInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# Pin the data dir to this repo's .job_agent so the dashboard always opens THIS
# database. Without the pin, a launch from an environment where HOME is set
# (Git Bash, some terminals) resolves to ~\.job_agent instead and the tracked
# jobs look deleted (2026-07-11 incident). An explicit env override still wins.
if (-not $env:JOB_AGENT_DATA_DIR) {
  $env:JOB_AGENT_DATA_DIR = Join-Path $Root ".job_agent"
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  Write-Host "Creating local Python environment..."
  py -3 -m venv .venv
}

$Python = Resolve-Path ".\.venv\Scripts\python.exe"

if (-not $NoInstall) {
  Write-Host "Installing/updating local package dependencies..."
  & $Python -m pip install -q --upgrade pip
  & $Python -m pip install -q -e .
}

Write-Host ""
Write-Host "Starting Job Agent dashboard..."
Write-Host "Open: http://127.0.0.1:$Port"
Write-Host "Stop: press Ctrl+C in this terminal."
Write-Host ""

& $Python -m job_agent.ui.server --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "The dashboard exited with an error (code $LASTEXITCODE) - see the message above." -ForegroundColor Red
  Read-Host "Press Enter to close"
}
