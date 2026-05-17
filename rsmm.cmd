@echo off
REM Windows CMD wrapper for rsmm
SETLOCAL
set SCRIPT_DIR=%~dp0

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 "%SCRIPT_DIR%rsmm" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  python "%SCRIPT_DIR%rsmm" %*
  exit /b %ERRORLEVEL%
)

echo Python 3 not found. Install Python 3 or use the py launcher.
exit /b 1
