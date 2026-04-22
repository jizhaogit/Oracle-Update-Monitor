@echo off
setlocal EnableDelayedExpansion
title Oracle OCI/OIC Monitor
:: Always run relative to this script's folder
cd /d "%~dp0"

echo.
echo  =====================================================
echo   Oracle OCI / OIC Monitor  [Portable]
echo  =====================================================
echo.

:: ════════════════════════════════════════════════════════
:: STEP 1 — Locate or download a Python runtime
:: ════════════════════════════════════════════════════════

set PYTHON=runtime\python.exe

if exist "%PYTHON%" (
    echo  [OK] Portable Python runtime found.
    echo.
    goto :check_packages
)

:: ── No bundled runtime yet — set it up now ───────────────
echo  [..] First-time setup: downloading portable Python runtime...
echo      This happens once and takes about 1-2 minutes.
echo.

:: Need PowerShell for downloading (available on all Windows 7+)
powershell -NoProfile -Command "exit 0" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  [ERROR] PowerShell is required for first-time setup but was not found.
    pause & exit /b 1
)

:: Download Python 3.11.9 embeddable (stable LTS, ~8 MB)
set PY_VER=3.11.9
set PY_ZIP=python-%PY_VER%-embed-amd64.zip
set PY_URL=https://www.python.org/ftp/python/%PY_VER%/%PY_ZIP%

echo  [..] Downloading Python %PY_VER% embeddable package (~8 MB)...
powershell -NoProfile -Command ^
    "try { Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_ZIP%' -UseBasicParsing } " ^
    "catch { Write-Host $_.Exception.Message; exit 1 }"
if %ERRORLEVEL% neq 0 (
    echo.
    echo  [ERROR] Download failed. Check your internet connection.
    if exist "%PY_ZIP%" del /f /q "%PY_ZIP%"
    pause & exit /b 1
)

:: Extract
echo  [..] Extracting runtime...
if exist runtime rmdir /s /q runtime
mkdir runtime
powershell -NoProfile -Command ^
    "Expand-Archive -Path '%PY_ZIP%' -DestinationPath 'runtime' -Force"
del /f /q "%PY_ZIP%" >nul 2>&1

if not exist "runtime\python.exe" (
    echo  [ERROR] Extraction failed — python.exe not found in runtime\.
    pause & exit /b 1
)

:: Enable site-packages so pip-installed packages are importable
echo  [..] Configuring runtime...
powershell -NoProfile -Command ^
    "(Get-Content 'runtime\python311._pth') -replace '#import site','import site' " ^
    "| Set-Content 'runtime\python311._pth'"

:: Bootstrap pip
echo  [..] Installing pip into runtime...
powershell -NoProfile -Command ^
    "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' " ^
    "-OutFile 'get-pip.py' -UseBasicParsing"
runtime\python.exe get-pip.py --no-warn-script-location --quiet
del /f /q get-pip.py >nul 2>&1

echo  [OK] Portable Python %PY_VER% runtime is ready.
echo.

:: ════════════════════════════════════════════════════════
:: STEP 2 — Install Python packages (first run or missing)
:: ════════════════════════════════════════════════════════

:check_packages
:: Quick exit if packages are already present
runtime\python.exe -c "import sqlalchemy, fastapi, apscheduler" >nul 2>&1
if %ERRORLEVEL%==0 (
    echo  [OK] Packages already installed.
    echo.
    goto :setup_env
)

:: ── Prepare site-packages directory ───────────────────────────
if not exist "runtime\Lib\site-packages" mkdir "runtime\Lib\site-packages"

:: Write a clean _pth that explicitly includes Lib\site-packages
:: (more reliable than relying on "import site" discovery)
(
    echo python311.zip
    echo .
    echo Lib\site-packages
    echo.
    echo import site
) > "runtime\python311._pth"

:: ── Locate system Python with pip ─────────────────────────────
set SYS_PYTHON=
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set SYS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe
if not defined SYS_PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set SYS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe
if not defined SYS_PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set SYS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not defined SYS_PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set SYS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe
if not defined SYS_PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set SYS_PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe
if not defined SYS_PYTHON if exist "%PROGRAMFILES%\Python314\python.exe" set SYS_PYTHON=%PROGRAMFILES%\Python314\python.exe
if not defined SYS_PYTHON if exist "%PROGRAMFILES%\Python313\python.exe" set SYS_PYTHON=%PROGRAMFILES%\Python313\python.exe
if not defined SYS_PYTHON if exist "%PROGRAMFILES%\Python312\python.exe" set SYS_PYTHON=%PROGRAMFILES%\Python312\python.exe

if not defined SYS_PYTHON (
    echo  [ERROR] No system Python found to install packages.
    echo.
    echo  Please install Python 3.9+ from https://www.python.org/downloads/
    echo  then run run.bat again.
    echo.
    echo  OR install packages manually on any machine with internet access:
    echo    python -m pip install -r requirements-core.txt --target runtime\Lib\site-packages
    echo.
    pause & exit /b 1
)

echo  [..] Installing packages using: %SYS_PYTHON%
echo      (sqlalchemy, langchain, fastapi, beautifulsoup4, uvicorn, APScheduler...)
echo      This takes several minutes on first run...
echo.

"%SYS_PYTHON%" -m pip install -r requirements-core.txt ^
    --target "runtime\Lib\site-packages" ^
    --python-version 3.11 --abi cp311 --platform win_amd64 --only-binary :all: ^
    --no-warn-script-location ^
    --disable-pip-version-check

:: Verify
runtime\python.exe -c "import sqlalchemy, fastapi, apscheduler" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo  [ERROR] Package installation failed.
    echo  Try running this manually and check for errors:
    echo    "%SYS_PYTHON%" -m pip install -r requirements-core.txt --target runtime\Lib\site-packages
    pause & exit /b 1
)
echo.
echo  [OK] Packages installed and verified.
echo.

:: ════════════════════════════════════════════════════════
:: STEP 3 — One-time environment setup
:: ════════════════════════════════════════════════════════

:setup_env
if not exist ".env" (
    copy .env.example .env >nul
    echo  [OK] Created .env with default settings.
    echo.
)

if not exist "data\db\oracle_monitor.db" (
    echo  [..] First run — loading sample Oracle OCI/OIC data...
    runtime\python.exe main.py --seed
    echo  [OK] Sample data loaded.
    echo.
)

:: ════════════════════════════════════════════════════════
:: STEP 4 — Launch the application
:: ════════════════════════════════════════════════════════
echo  =====================================================
echo  [..] Starting server + opening browser UI...
echo  =====================================================
echo.
echo  The app will open automatically in your browser.
echo  Keep this window open while using the app.
echo  Press Ctrl+C here to stop the server.
echo.
runtime\python.exe main.py %*

echo.
echo  Server stopped.
pause
