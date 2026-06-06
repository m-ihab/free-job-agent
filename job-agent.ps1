param()

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Exe = Join-Path $Root ".venv\Scripts\job-agent.exe"
if (Test-Path $Exe) {
    & $Exe @args
} else {
    & (Join-Path $Root ".venv\Scripts\python.exe") -m job_agent.cli.main @args
}
