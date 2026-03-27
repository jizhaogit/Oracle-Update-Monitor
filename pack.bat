@echo off
setlocal EnableDelayedExpansion
title Oracle OCI/OIC Monitor — Pack Portable
cd /d "%~dp0"

echo.
echo  =====================================================
echo   Oracle OCI/OIC Monitor — Build Portable Package
echo  =====================================================
echo.

:: ── Check runtime exists ─────────────────────────────────
if not exist "runtime\python.exe" (
    echo  [ERROR] Portable runtime not found.
    echo  Run run.bat first to set up the runtime, then run pack.bat.
    pause & exit /b 1
)

:: ── Verify packages are installed ────────────────────────
runtime\python.exe -c "import sqlalchemy, fastapi" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  [ERROR] Packages not installed in runtime.
    echo  Run run.bat first to install packages, then run pack.bat.
    pause & exit /b 1
)

:: ── Clean up temp files before packing ───────────────────
echo  [..] Cleaning temporary files...
for /d /r . %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d" >nul 2>&1
)
for /r . %%f in (*.pyc *.pyo) do del /f /q "%%f" >nul 2>&1

:: Remove log files (keep folder)
if exist "logs" del /f /q "logs\*.log" >nul 2>&1

:: Remove raw crawl cache (optional — keeps package small)
if exist "data\raw" rmdir /s /q "data\raw" >nul 2>&1
mkdir "data\raw" >nul 2>&1

echo  [OK] Cleanup done.
echo.

:: ── Create output zip ─────────────────────────────────────
set ZIPNAME=OracleMonitor_portable.zip
if exist "%ZIPNAME%" del /f /q "%ZIPNAME%"

echo  [..] Building %ZIPNAME% ...
echo      (This may take a minute — runtime folder can be several hundred MB)
echo.

powershell -NoProfile -Command ^
    "$src = Get-Location; " ^
    "$exclude = @('.venv', '.git', '__pycache__', '*.pyc', 'OracleMonitor_portable.zip'); " ^
    "$items = Get-ChildItem -Path $src -Exclude $exclude; " ^
    "Compress-Archive -Path $items -DestinationPath '%ZIPNAME%' -Force; " ^
    "Write-Host ('  Size: ' + [math]::Round((Get-Item '%ZIPNAME%').Length/1MB, 1) + ' MB')"

if not exist "%ZIPNAME%" (
    echo  [ERROR] Failed to create zip file.
    pause & exit /b 1
)

:: ── Done ──────────────────────────────────────────────────
echo.
echo  =====================================================
echo  [OK] Portable package ready: %ZIPNAME%
echo.
echo  To deploy on another computer:
echo    1. Copy %ZIPNAME% to the target machine
echo    2. Extract the zip to any folder
echo    3. Double-click run.bat
echo       (No Python install needed — runtime is bundled)
echo  =====================================================
echo.
pause
