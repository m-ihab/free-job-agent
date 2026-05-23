param(
  [int]$Port = 8765,
  [switch]$NoInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

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
