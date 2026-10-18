# Experimental Harborforge lab installer; never overwrites Deckhand.
$ErrorActionPreference = 'Stop'
$src = Join-Path $PSScriptRoot 'skills\harborforge'
if (-not (Test-Path (Join-Path $src 'SKILL.md'))) { throw 'Missing Harborforge skill' }
$targets = @("$HOME\.claude\skills", "$HOME\.codex\skills", "$HOME\.agents\skills", "$HOME\.cursor\skills", "$HOME\.hermes\skills", "$HOME\.gemini\skills", "$HOME\.config\opencode\skills")
foreach ($dir in $targets) {
  if (-not (Test-Path (Split-Path $dir -Parent))) { continue }
  New-Item -ItemType Directory -Force $dir | Out-Null
  $dest = Join-Path $dir 'harborforge'
  if (Test-Path $dest) { Write-Warning "Skipped existing Harborforge installation: $dest"; continue }
  Copy-Item -Recurse $src $dest
  Write-Host "Installed Harborforge: $dest"
}
$state = Join-Path $HOME '.harborforge'
$dest = Join-Path $state 'skill\harborforge'
if (Test-Path $dest) { throw "Refusing to overwrite $dest" }
New-Item -ItemType Directory -Force (Join-Path $state 'bin'), (Split-Path $dest -Parent) | Out-Null
Copy-Item -Recurse $src $dest
$shim = Join-Path $state 'bin\hf.cmd'
$cmd = @'
@echo off
if "%HARBORFORGE_HOME%"=="" (
  set "DECKHAND_HOME=%USERPROFILE%\.harborforge\state"
) else (
  set "DECKHAND_HOME=%HARBORFORGE_HOME%"
)
py "%USERPROFILE%\.harborforge\skill\harborforge\dh.py" %*
'@
Set-Content -Path $shim -Value $cmd -Encoding Ascii
Write-Host "Harborforge lab ready: $shim next"
Write-Warning 'Do not use Harborforge in an existing Deckhand project while project-state namespacing remains unfinished.'
