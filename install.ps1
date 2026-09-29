# Deckhand installer (Windows) - copies skills\deckhand into every agent harness found and adds a dh.cmd shim.
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-Link] [-Only claude,hermes] [-ClaudeHook]
#   -ClaudeHook: every Claude Code session in a deckhand project starts from its .deckhand/RESUME.md
param([switch]$Link, [string]$Only = "", [switch]$ClaudeHook)
$ErrorActionPreference = "Stop"
$Src = Join-Path $PSScriptRoot "skills\deckhand"
# A -Link install is a junction: PowerShell 5.1's Remove-Item -Recurse follows it and empties the clone, so drop only the link
function Remove-Install($p) {
  if (-not (Test-Path $p)) { return }
  $item = Get-Item $p -Force
  if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { $item.Delete() } else { Remove-Item -Recurse -Force $p }
}
foreach ($t in @(@("py","Python 3.9+ (the py launcher)"), @("node","Node 18+ (try-on, compose)"), @("git","git"))) {
  if (-not (Get-Command $t[0] -ErrorAction SilentlyContinue)) { Write-Host "missing: $($t[0]) - $($t[1])" }
}
$targets = @(
  @("claude",  "$HOME\.claude\skills"),
  @("codex",   "$HOME\.codex\skills"),
  @("agents",  "$HOME\.agents\skills"),
  @("cursor",  "$HOME\.cursor\skills"),
  @("hermes",  "$env:LOCALAPPDATA\hermes\skills"),
  @("hermes",  "$HOME\.hermes\skills"),
  @("opencode","$HOME\.config\opencode\skills"),
  @("gemini",  "$HOME\.gemini\skills")
)
foreach ($t in $targets) {
  $name, $dir = $t
  if ($Only -and -not ((",$Only,") -like "*,$name,*")) { continue }
  $parent = Split-Path $dir -Parent
  if (-not (Test-Path $parent) -and $name -ne "agents") { continue }
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $dest = Join-Path $dir "deckhand"
  # Hermes files skills under categories (skills\software-development\deckhand): update that copy, never add a second one
  $nested = Get-ChildItem -Path $dir -Directory -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.FullName "deckhand\SKILL.md" } |
            Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($nested -and -not (Test-Path (Join-Path $dest "SKILL.md"))) { $dest = Split-Path $nested -Parent }
  Remove-Install $dest
  if ($Link) { New-Item -ItemType Junction -Path $dest -Target $Src | Out-Null } else { Copy-Item -Recurse $Src $dest }
  Write-Host "OK $name -> $dest"
}
$bin = "$HOME\.deckhand\bin"
$stable = "$HOME\.deckhand\skill\deckhand"
New-Item -ItemType Directory -Force -Path $bin, (Split-Path $stable -Parent) | Out-Null
Remove-Install $stable
if ($Link) { New-Item -ItemType Junction -Path $stable -Target $Src | Out-Null } else { Copy-Item -Recurse $Src $stable }
Set-Content -Path "$bin\dh.cmd" -Value "@py `"$stable\dh.py`" %*" -Encoding ASCII
Write-Host "OK dh shim -> $bin\dh.cmd  (add $bin to PATH)"
if ($ClaudeHook) {
  & py "$stable\dh.py" resume --install-hook claude | Out-Null
  Write-Host "OK Claude Code SessionStart hook (sessions in a deckhand project start from .deckhand/RESUME.md)"
} else { Write-Host "(optional) -ClaudeHook: Claude Code sessions in a deckhand project then start from its RESUME" }
Write-Host "Next: open your agent and say what you want, e.g. 'Build a website for my bakery. Phased mode.'"
Write-Host "Step by step, copy-a-sentence: docs/USE-CASES.md"
