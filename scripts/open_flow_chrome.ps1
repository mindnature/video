# Start an isolated local Chrome instance for Gemini and Google Flow; user signs in manually.
# Never expose port 9222 beyond the loopback interface.
$ErrorActionPreference = 'Stop'
$chromeCandidates = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chrome = $chromeCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $chrome) { throw 'Chrome not found. Install Google Chrome and retry.' }
$profile = Join-Path $env:LOCALAPPDATA 'VideoStudio-Flow-Profile'
New-Item -ItemType Directory -Force -Path $profile | Out-Null
$arguments = @(
  '--remote-debugging-address=127.0.0.1',
  '--remote-debugging-port=9222',
  "--user-data-dir=$profile",
  'https://gemini.google.com/app',
  'https://labs.google/fx/tools/flow'
)
Start-Process -FilePath $chrome -ArgumentList $arguments
Write-Host 'Opened dedicated Gemini + Flow Chrome profile; sign in to both websites and configure Flow mode.'
Write-Host 'CDP is local on 127.0.0.1:9222. Do not forward this port or store credentials in the repo.'
