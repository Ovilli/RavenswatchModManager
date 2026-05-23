@echo off
REM Build the Windows mod-manager DLL using Visual Studio or MinGW on Windows
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

REM Configure with CMake - auto-detect toolchain (Visual Studio or MinGW)
echo Configuring with CMake...
cd /d "%BUILD%"
cmake .. -DCMAKE_BUILD_TYPE=Release
if errorlevel 1 (
    echo CMake configuration failed
    exit /b 1
)

REM Build
echo Building...
cmake --build . --config Release
if errorlevel 1 (
    echo Build failed
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
