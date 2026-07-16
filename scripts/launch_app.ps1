param(
  [string]$Url = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Stop"

$commandCandidates = @("chrome.exe", "msedge.exe") | ForEach-Object {
  $command = Get-Command $_ -ErrorAction SilentlyContinue
  if ($command) { $command.Source }
}
$pathCandidates = @()
foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
  if (-not $root) { continue }
  $pathCandidates += Join-Path $root "Google\Chrome\Application\chrome.exe"
  $pathCandidates += Join-Path $root "Microsoft\Edge\Application\msedge.exe"
}
$browser = @($commandCandidates + $pathCandidates) |
  Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
  Select-Object -First 1

if ($browser) {
  Start-Process -FilePath $browser -ArgumentList "--app=$Url"
  exit 0
}

Start-Process $Url
