@echo off
REM Fetch third-party dependencies for the Ravenswatch Mod Manager loader on Windows.
setlocal enabledelayedexpansion

set "HERE=%~dp0"
set "TP=%HERE%third_party"

if not exist "%TP%" mkdir "%TP%"

REM Function to clone or update a git repo
setlocal enabledelayedexpansion
goto :start

:clone_repo
setlocal enabledelayedexpansion
set "REPO=%1"
set "DEST=%2"
set "REV=%3"

if not exist "%DEST%\.git" (
    echo Cloning %REPO% to %DEST%...
    git clone --depth 1 "%REPO%" "%DEST%"
    if errorlevel 1 (
        echo Failed to clone %REPO%
        exit /b 1
    )
)

if not "!REV!"=="" (
    echo Checking out %REV% in %DEST%...
    cd /d "%DEST%"
    git fetch --depth 1 origin "!REV!"
    git checkout "!REV!"
    cd /d "%HERE%"
)
exit /b 0

:start
REM Clone main dependencies
call :clone_repo "https://github.com/TsudaKageyu/minhook" "%TP%\minhook"
call :clone_repo "https://github.com/ocornut/imgui" "%TP%\imgui"
call :clone_repo "https://github.com/KhronosGroup/Vulkan-Headers" "%TP%\Vulkan-Headers"
call :clone_repo "https://github.com/lua/lua" "%TP%\lua"

REM Download header-only libraries
if not exist "%TP%\nlohmann" mkdir "%TP%\nlohmann"
if not exist "%TP%\tomlplusplus" mkdir "%TP%\tomlplusplus"

echo Downloading nlohmann/json...
powershell -Command "[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://github.com/nlohmann/json/releases/latest/download/json.hpp' -OutFile '%TP%\nlohmann\json.hpp'"
if errorlevel 1 (
    echo Warning: Failed to download json.hpp, but continuing...
)

echo Downloading tomlplusplus...
powershell -Command "[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/marzer/tomlplusplus/master/toml.hpp' -OutFile '%TP%\tomlplusplus\toml.hpp'"
if errorlevel 1 (
    echo Warning: Failed to download toml.hpp, but continuing...
)

echo.
echo Dependencies fetched successfully to: %TP%
endlocal
