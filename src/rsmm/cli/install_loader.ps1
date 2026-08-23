param(
  [string] $GameDir
)

# Install the mod manager into the Ravenswatch game directory (native Windows).
set-StrictMode -Version Latest

# If no game dir given, error out — Windows users should pass the install path.
if (-not $GameDir) {
  Write-Error "Usage: install_loader.ps1 <game-dir>"; exit 1
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoDir = Resolve-Path (Join-Path $scriptDir '..\..\..')
$repoDir = $repoDir.Path

$gameExe = Join-Path $GameDir 'Ravenswatch.exe'
if (-not (Test-Path $gameExe)) {
  Write-Error "Ravenswatch.exe not found in: $GameDir"; exit 1
}

$dll = Join-Path $repoDir 'dist\winhttp.dll'
if (-not (Test-Path $dll)) {
  Write-Error "Build first: loader/build.sh (produce dist\winhttp.dll)"; exit 1
}

# If winhttp_real.dll missing, try to source a real one.
if (-not (Test-Path (Join-Path $GameDir 'winhttp_real.dll'))) {
  # Prefer native Windows system DLLs when available (for native Windows installs).
  $systemCandidates = @(
    "$env:windir\System32\winhttp.dll",
    "$env:windir\SysWOW64\winhttp.dll"
  )
  foreach ($c in $systemCandidates) {
    if ($c -and (Test-Path $c)) {
      Copy-Item -Path $c -Destination (Join-Path $GameDir 'winhttp_real.dll') -Force
      Write-Host "Sourced winhttp_real.dll from: $c"
      break
    }
  }

  if (-not (Test-Path (Join-Path $GameDir 'winhttp_real.dll'))) {
    # Fall back to Proton/Wine locations (useful when running under WSL/Flatpak Proton prefixes).
    $candidates = @(
      "$env:USERPROFILE\.var\app\com.valvesoftware.Steam\.local\share\Steam\steamapps\compatdata\2071280\pfx\drive_c\windows\system32\winhttp.dll",
      "$env:USERPROFILE\.var\app\com.valvesoftware.Steam\.local\share\Steam\steamapps\common\Proton Hotfix\files\lib\wine\x86_64-windows\winhttp.dll",
      "$env:USERPROFILE\.steam\steam\steamapps\common\Proton - Experimental\files\lib\wine\x86_64-windows\winhttp.dll"
    )
    foreach ($c in $candidates) {
      if (Test-Path $c) {
        Copy-Item -Path $c -Destination (Join-Path $GameDir 'winhttp_real.dll') -Force
        Write-Host "Sourced winhttp_real.dll from: $c"
        break
      }
    }
  }

  if (-not (Test-Path (Join-Path $GameDir 'winhttp_real.dll'))) {
    Write-Error "ERROR: could not find a real winhttp.dll to use as winhttp_real.dll"; exit 1
  }
}

# If existing winhttp.dll looks like Doorstop (contains 'doorstop.dll' text), remove it.
# Works on Windows PowerShell 5.x AND PowerShell 7+ (avoids `-Encoding Byte` which
# was removed in PS 7).
function Is-Doorstop($path) {
  try {
    $bytes = [System.IO.File]::ReadAllBytes($path)
    $text = [System.Text.Encoding]::ASCII.GetString($bytes)
    return ($text -match 'doorstop.dll')
  } catch { return $false }
}

$winhttp = Join-Path $GameDir 'winhttp.dll'
$winhttp_real = Join-Path $GameDir 'winhttp_real.dll'
if ((Test-Path $winhttp) -and (Is-Doorstop $winhttp)) {
  Remove-Item $winhttp -Force
  Write-Host "Removing BepInEx/Doorstop winhttp.dll"
}
if ((Test-Path $winhttp_real) -and (Is-Doorstop $winhttp_real)) {
  Remove-Item $winhttp_real -Force
  Write-Host "Removing BepInEx/Doorstop winhttp_real.dll"
}

Copy-Item -Path $dll -Destination $winhttp -Force
Copy-Item -Path (Join-Path $repoDir 'data\asset_map.json') -Destination (Join-Path $GameDir 'asset_map.json') -Force
$dataDst = Join-Path $GameDir 'rsmm\data'
New-Item -ItemType Directory -Path $dataDst -Force | Out-Null
Copy-Item -Path (Join-Path $repoDir 'data\function_patterns.json') -Destination (Join-Path $dataDst 'function_patterns.json') -Force
$patternsMeta = Join-Path $repoDir 'data\function_patterns.meta.json'
if (Test-Path $patternsMeta) {
  Copy-Item -Path $patternsMeta -Destination (Join-Path $dataDst 'function_patterns.meta.json') -Force
}

# Lua-side SDK: mods do `require "rsmm"` and get the documented R.* surface.
$luaSrc = Join-Path $repoDir 'src\loader\lua'
$luaDst = Join-Path $GameDir 'rsmm\lib'
if (Test-Path $luaSrc) {
  New-Item -ItemType Directory -Path $luaDst -Force | Out-Null
  Copy-Item -Path (Join-Path $luaSrc '*') -Destination $luaDst -Recurse -Force
}
# lua/ ships the rsmm/*.lua submodules lib/rsmm.lua pulls in
# (health/config/i18n/api/schedule, plus damage, which is 45% of the SDK by
# line count and is required, not merged). Install the entrypoint + engine table
# (R.engine.* resolves names through it) from lib/. Mirrors install_loader.sh;
# both lua/ and lib/ are bundled into the frozen sidecar.
New-Item -ItemType Directory -Path $luaDst -Force | Out-Null
$fullRsmm = Join-Path $repoDir 'src\loader\lib\rsmm.lua'
if (Test-Path $fullRsmm) {
  Copy-Item -Path $fullRsmm -Destination (Join-Path $luaDst 'rsmm.lua') -Force
}
$engineGen = Join-Path $repoDir 'src\loader\lib\engine_gen.lua'
if (Test-Path $engineGen) {
  Copy-Item -Path $engineGen -Destination (Join-Path $luaDst 'engine_gen.lua') -Force
}
# rsmm.lua does `pcall(require, "events_gen")` — a pcall, so a missing file is
# silent and R.events.known() just returns nothing. It was never planted.
$eventsGen = Join-Path $repoDir 'src\loader\lib\events_gen.lua'
if (Test-Path $eventsGen) {
  Copy-Item -Path $eventsGen -Destination (Join-Path $luaDst 'events_gen.lua') -Force
}

# Sync mod manifests + init.lua
New-Item -ItemType Directory -Path (Join-Path $GameDir 'mods') -Force | Out-Null
Get-ChildItem -Directory (Join-Path $repoDir 'mods') | ForEach-Object {
  $m = Join-Path $_.FullName 'manifest.toml'
  if (Test-Path $m) {
    $dst = Join-Path $GameDir (Join-Path 'mods' $_.Name)
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    Copy-Item -Path $m -Destination (Join-Path $dst 'manifest.toml') -Force
    $init = Join-Path $_.FullName 'init.lua'
    if (Test-Path $init) { Copy-Item -Path $init -Destination (Join-Path $dst 'init.lua') -Force }
    $ptrs = Join-Path $_.FullName 'pointers.json'
    if (Test-Path $ptrs) { Copy-Item -Path $ptrs -Destination (Join-Path $dst 'pointers.json') -Force }
    # User config so the loader's config_get bindings see it in-game.
    $cfg = Join-Path $_.FullName 'config.toml'
    if (Test-Path $cfg) { Copy-Item -Path $cfg -Destination (Join-Path $dst 'config.toml') -Force }
  }
}

# Disable Doorstop config if present
$door = Join-Path $GameDir 'doorstop_config.ini'
if (Test-Path $door) {
  (Get-Content $door) -replace '^enabled\s*=.*', 'enabled = false' | Set-Content $door
}

Write-Host "Installed mod manager into $GameDir"
exit 0
