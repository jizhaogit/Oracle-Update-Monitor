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
:: STEP 0 — Detect corporate proxy
::
::  pip does NOT understand PAC files — it needs a real
::  http://host:port address.  We try three methods:
::    1. Windows system/WPAD proxy  (set by Group Policy)
::    2. Resolve PAC file from HTTPS_PROXY in .env
::    3. Use HTTPS_PROXY directly if it is already host:port
:: ════════════════════════════════════════════════════════

set RESOLVED_PROXY=
set PIP_PROXY_FLAG=
set RAW_PROXY=

:: Read HTTPS_PROXY value from .env (if file exists)
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (`findstr /i "^HTTPS_PROXY=" .env`) do (
        set RAW_PROXY=%%B
    )
)

:: ── Method 1: Windows system proxy (Group Policy / WPAD) ──────────────────
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command ^
    "try { $p=[System.Net.WebRequest]::GetSystemWebProxy().GetProxy('https://pypi.org'); " ^
    "if ($p.Host -and $p.Host -ne 'pypi.org') { 'http://'+$p.Host+':'+$p.Port } else { '' } } catch { '' }"`) do (
    if not "%%P"=="" set RESOLVED_PROXY=%%P
)

:: ── Method 2/3: Use HTTPS_PROXY from .env ─────────────────────────────────
if not defined RESOLVED_PROXY (
    if defined RAW_PROXY (
        :: Check if it is a PAC file URL (contains .pac)
        echo !RAW_PROXY! | findstr /i "\.pac" >nul 2>&1
        if !ERRORLEVEL!==0 (
            echo  [..] Resolving PAC proxy: !RAW_PROXY!
            for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command ^
                "try { $c=(Invoke-WebRequest -Uri '!RAW_PROXY!' -UseBasicParsing -TimeoutSec 8).Content;" ^
                "if ($c -match 'PROXY\s+([\w.\-]+:\d+)') { 'http://'+$Matches[1] } else { '' } } catch { '' }"`) do (
                if not "%%P"=="" set RESOLVED_PROXY=%%P
            )
            if defined RESOLVED_PROXY (
                echo  [OK] Resolved proxy: !RESOLVED_PROXY!
            ) else (
                echo  [WARN] Could not resolve PAC file - will try without proxy
            )
        ) else (
            :: It is already a real host:port proxy URL
            set RESOLVED_PROXY=!RAW_PROXY!
            echo  [OK] Using proxy from .env: !RESOLVED_PROXY!
        )
    )
)

:: ── Set proxy env vars for pip and Python ─────────────────────────────────
if defined RESOLVED_PROXY (
    set HTTPS_PROXY=!RESOLVED_PROXY!
    set HTTP_PROXY=!RESOLVED_PROXY!
    set PIP_PROXY_FLAG=--proxy !RESOLVED_PROXY!
    echo  [OK] Proxy configured for downloads and pip: !RESOLVED_PROXY!
) else (
    echo  [OK] No proxy needed ^(or not on VPN^)
)
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
    "try { $uri='%PY_URL%'; $out='%PY_ZIP%'; $proxy='!RESOLVED_PROXY!';" ^
    "$wc=New-Object System.Net.WebClient;" ^
    "if($proxy){$wc.Proxy=New-Object System.Net.WebProxy($proxy,$true)};" ^
    "$wc.DownloadFile($uri,$out); Write-Host '[OK] Download complete' } " ^
    "catch { Write-Host '[ERROR]'$_.Exception.Message; exit 1 }"
if %ERRORLEVEL% neq 0 (
    echo.
    echo  [ERROR] Download failed. Check your internet/VPN connection.
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

:: Bootstrap pip (with proxy if needed)
echo  [..] Installing pip into runtime...
powershell -NoProfile -Command ^
    "try { $uri='https://bootstrap.pypa.io/get-pip.py'; $out='get-pip.py'; $proxy='!RESOLVED_PROXY!';" ^
    "$wc=New-Object System.Net.WebClient;" ^
    "if($proxy){$wc.Proxy=New-Object System.Net.WebProxy($proxy,$true)};" ^
    "$wc.DownloadFile($uri,$out) } " ^
    "catch { Write-Host '[ERROR]'$_.Exception.Message; exit 1 }"
runtime\python.exe get-pip.py --no-warn-script-location --quiet !PIP_PROXY_FLAG!
del /f /q get-pip.py >nul 2>&1

echo  [OK] Portable Python %PY_VER% runtime is ready.
echo.

:: ════════════════════════════════════════════════════════
:: STEP 2 — Install Python packages (first run or missing)
:: ════════════════════════════════════════════════════════

:check_packages
runtime\python.exe -c "import sqlalchemy, fastapi, apscheduler" >nul 2>&1
if %ERRORLEVEL%==0 (
    echo  [OK] Packages already installed.
    echo.
    goto :setup_env
)

echo  [..] Installing packages — this takes several minutes the first time...
echo      (sqlalchemy, langchain, fastapi, beautifulsoup4, uvicorn, APScheduler...)
echo.
runtime\python.exe -m pip install -r requirements-core.txt ^
    !PIP_PROXY_FLAG! ^
    --trusted-host pypi.org ^
    --trusted-host pypi.python.org ^
    --trusted-host files.pythonhosted.org ^
    --no-warn-script-location ^
    --disable-pip-version-check

:: Verify — do NOT rely on pip exit code (can be non-zero even on success)
runtime\python.exe -c "import sqlalchemy, fastapi, apscheduler" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo  [ERROR] Package installation failed.
    echo  Check your internet/VPN connection and try again, or run:
    echo    runtime\python.exe -m pip install -r requirements-core.txt !PIP_PROXY_FLAG!
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
