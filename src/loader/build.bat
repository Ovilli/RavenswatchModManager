@echo off
REM Build the Windows mod-manager DLL. Prefers MinGW (handles .def
REM forwarder exports correctly); falls back to MSVC (the .def file
REM uses forwarder entries that MSVC's linker can't resolve, so the
REM DLL won't export those functions — the sidecar bundler handles
RETurn this gracefully by skipping if dist/winhttp.dll is missing).
setlocal enabledelayedexpansion

set "HERE=%~dp0"
set "BUILD=%HERE%build"
REM Walk up from src\loader\ to repo root, then dist\. (build.sh mirrors this.)
set "DIST=%HERE%..\..\dist"

REM Check if dependencies are fetched
if not exist "%HERE%third_party\minhook\src\hook.c" (
    echo Fetching dependencies...
    call "%HERE%fetch_deps.bat"
    if errorlevel 1 exit /b 1
)

REM Create build directory
if not exist "%BUILD%" mkdir "%BUILD%"

REM Detect MinGW (preferred for .def forwarder exports)
set "BUILD_TOOL="
where gcc >nul 2>nul
if %errorlevel% equ 0 set BUILD_TOOL=mingw
where mingw32-make >nul 2>nul
if %errorlevel% equ 0 set BUILD_TOOL=mingw

REM Configure with CMake - use MinGW if available
echo Configuring with CMake...
cd /d "%BUILD%"

if "%BUILD_TOOL%"=="mingw" (
    echo Using MinGW toolchain
    cmake .. -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
) else (
    echo Using MSVC toolchain (forwarder exports may fail — that's OK)
    cmake .. -DCMAKE_BUILD_TYPE=Release
)
if errorlevel 1 (
    echo CMake configuration failed
    exit /b 1
)

REM Build
echo Building...
cmake --build . --config Release
if errorlevel 1 (
    echo Build failed
    echo NOTE: MSVC cannot resolve .def forwarder symbols. Install MinGW
    echo       (choco install mingw) or expect the DLL to be missing from dist/.
    exit /b 1
)

REM Copy to dist
if not exist "%DIST%" mkdir "%DIST%"
if exist "%BUILD%\Release\winhttp.dll" (
    copy "%BUILD%\Release\winhttp.dll" "%DIST%\winhttp.dll"
) else if exist "%BUILD%\winhttp.dll" (
    copy "%BUILD%\winhttp.dll" "%DIST%\winhttp.dll"
) else (
    echo Could not find built winhttp.dll
    exit /b 1
)

echo.
echo Built: %DIST%\winhttp.dll
endlocal
