@echo off
REM Install the mod manager into the Ravenswatch game directory.
REM Backs up the original winhttp.dll (if any) and installs our proxy DLL.
setlocal enabledelayedexpansion

REM Get game directory from argument or use default Steam path
if "%1"=="" (
    set "GAME_DIR=%USERPROFILE%\.var\app\com.valvesoftware.Steam\.local\share\Steam\steamapps\common\Ravenswatch"
) else (
    set "GAME_DIR=%1"
)

REM Get repo directory
for %%I in ("%~dp0..\..\..") do set "REPO_DIR=%%~fI"

REM Check if game executable exists
if not exist "%GAME_DIR%\Ravenswatch.exe" (
    echo Error: Ravenswatch.exe not found in: %GAME_DIR%
    exit /b 1
)

REM Check if built DLL exists
set "DLL=%REPO_DIR%\dist\winhttp.dll"
if not exist "%DLL%" (
    echo Error: Build first with build.bat
    exit /b 1
)

REM Backup existing DLL if needed
if exist "%GAME_DIR%\winhttp.dll" (
    echo Backing up existing winhttp.dll...
    move "%GAME_DIR%\winhttp.dll" "%GAME_DIR%\winhttp_backup.dll"
)

if exist "%GAME_DIR%\winhttp_real.dll" (
    echo Note: Found winhttp_real.dll (will use as forwarding target)
)

REM Copy our DLL
echo Installing loader to: %GAME_DIR%
copy /Y "%DLL%" "%GAME_DIR%\winhttp.dll"
if errorlevel 1 (
    echo Error: Failed to copy DLL
    exit /b 1
)

REM Copy asset map if not exists
if not exist "%GAME_DIR%\asset_map.json" (
    if exist "%REPO_DIR%\data\asset_map.json" (
        echo Copying asset_map.json...
        copy /Y "%REPO_DIR%\data\asset_map.json" "%GAME_DIR%\asset_map.json"
    )
)

REM Create mods directory if not exists
if not exist "%GAME_DIR%\mods" (
    mkdir "%GAME_DIR%\mods"
)

echo.
echo Loader installed successfully!
echo Game directory: %GAME_DIR%
echo.
echo Next steps:
echo 1. If using Steam, add launch options: WINEDLLOVERRIDES="winhttp=n,b" %%command%%
echo 2. Run the game with ./rsmm run or directly via Steam
echo.
endlocal
