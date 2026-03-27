@echo off
setlocal EnableDelayedExpansion
echo =========================================
echo  Oracle OCI/OIC Monitor - Install
echo =========================================
echo.

:: ── Locate Python ─────────────────────────────────────────────
set PYTHON=

:: 1. Try the Windows Python Launcher (py.exe) — most reliable
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set PYTHON=py
    echo [OK] Found Python via launcher: py
    goto :found_python
)

:: 2. Try python3
where python3 >nul 2>&1
if %ERRORLEVEL%==0 (
    set PYTHON=python3
    echo [OK] Found python3
    goto :found_python
)

:: 3. Search common install locations
for %%V in (313 312 311 310 39 38) do (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        "%PROGRAMFILES%\Python%%V\python.exe"
        "%PROGRAMFILES(x86)%\Python%%V\python.exe"
    ) do (
        if exist %%P (
            set PYTHON=%%P
            echo [OK] Found Python at %%P
            goto :found_python
        )
    )
)

:: 4. Microsoft Store Python (WindowsApps)
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" (
    set PYTHON="%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"
    echo [OK] Found Python (Microsoft Store)
    goto :found_python
)

:: Nothing found
echo.
echo [ERROR] Python not found on this machine.
echo.
echo  Please install Python 3.9+ from one of these sources:
echo    https://www.python.org/downloads/
echo    (tick "Add Python to PATH" during install)
echo.
echo  OR install via winget:
echo    winget install Python.Python.3.12
echo.
pause
exit /b 1

:found_python
:: Show version
%PYTHON% --version
echo.

:: ── Create virtual environment ────────────────────────────────
echo [..] Creating virtual environment (.venv)...
%PYTHON% -m venv .venv
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to create virtual environment.
    pause & exit /b 1
)
echo [OK] Virtual environment created.

:: ── Activate ──────────────────────────────────────────────────
call .venv\Scripts\activate.bat
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to activate virtual environment.
    pause & exit /b 1
)
echo [OK] Virtual environment activated.

:: ── Upgrade pip ───────────────────────────────────────────────
echo.
echo [..] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo [OK] pip upgraded.

:: ── Install dependencies ──────────────────────────────────────
echo.
echo [..] Installing dependencies (this may take a few minutes)...
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [ERROR] pip install failed. Check your internet connection.
    pause & exit /b 1
)
echo [OK] Dependencies installed.

:: ── Copy .env template ────────────────────────────────────────
if not exist .env (
    copy .env.example .env >nul
    echo [OK] Created .env from template
) else (
    echo [OK] .env already exists - skipping
)

:: ── Seed mock data ────────────────────────────────────────────
echo.
echo [..] Seeding initial mock data...
python main.py --seed
if %ERRORLEVEL% neq 0 (
    echo [WARN] Seed step failed - you can seed later with: python main.py --seed
) else (
    echo [OK] Mock data seeded.
)

echo.
echo =========================================
echo  Installation complete!
echo.
echo  To run the app:
echo    1. Double-click  run.bat
echo    OR
echo    1. Open a terminal in this folder
echo    2. .venv\Scripts\activate
echo    3. python main.py
echo =========================================
pause
