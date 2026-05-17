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

# If winhttp_real.dll missing, try to source a real one from common Proton/Wine locations
if (-not (Test-Path (Join-Path $GameDir 'winhttp_real.dll'))) {
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
  if (-not (Test-Path (Join-Path $GameDir 'winhttp_real.dll'))) {
    Write-Error "ERROR: could not find a real winhttp.dll to use as winhttp_real.dll"; exit 1
  }
}

# If existing winhttp.dll looks like Doorstop (contains 'doorstop.dll' text), remove it.
function Is-Doorstop($path) {
  try {
    $text = Get-Content -Raw -ErrorAction Stop $path -Encoding Byte
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
  }
}

# Disable Doorstop config if present
$door = Join-Path $GameDir 'doorstop_config.ini'
if (Test-Path $door) {
  (Get-Content $door) -replace '^enabled\s*=.*', 'enabled = false' | Set-Content $door
}

Write-Host "Installed mod manager into $GameDir"
exit 0
