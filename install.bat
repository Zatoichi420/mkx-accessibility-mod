@echo off
REM One-time setup: installs Python dependencies, adds a shortcut to your
REM Windows Startup folder so the reader starts quietly every time you log
REM in, and starts it right now too. After this, you never have to
REM remember to launch anything - the reader sits idle using almost no
REM resources until it sees MK10.exe appear, then starts talking. No Steam
REM launch options to configure, no external tool's settings to dig into
REM (unlike this project's GameCube sister projects, where that step was
REM the single biggest setup complaint). No admin rights needed either -
REM this uses your personal Startup folder, not Task Scheduler.
setlocal
cd /d "%~dp0"

echo Installing Python dependencies...
set "FALLBACK_PY=C:\Users\vegas\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\python.exe"
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set "PYEXE=py -3"
) else (
    where python >nul 2>&1
    if %ERRORLEVEL%==0 (
        set "PYEXE=python"
    ) else if exist "%FALLBACK_PY%" (
        set "PYEXE=%FALLBACK_PY%"
    ) else (
        echo.
        echo Python was not found on PATH. Install Python 3 from https://python.org
        echo ^(check "Add python.exe to PATH" during install^) and run this script again.
        pause
        exit /b 1
    )
)
%PYEXE% -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo pip install failed - see the error above. Setup did not complete.
    pause
    exit /b 1
)

echo Checking NVDA...
tasklist /FI "IMAGENAME eq nvda.exe" 2>nul | find /I "nvda.exe" >nul
if errorlevel 1 (
    echo NVDA does not appear to be running right now. That's fine for setup -
    echo the reader waits for NVDA at startup - but make sure NVDA is installed
    echo ^(https://www.nvaccess.org/download/^) before you plan to use this.
) else (
    echo NVDA is running. Good.
)

echo Adding a Startup-folder shortcut so the reader starts automatically...
cscript.exe //nologo "%~dp0ocr_reader\install_startup_shortcut.vbs"
if errorlevel 1 (
    echo.
    echo Could not create the Startup shortcut. You can still run it manually
    echo each time via ocr_reader\run_reader.bat.
) else (
    echo Done - it will start automatically every time you log into Windows.
)

echo Starting it now for this session too...
wscript.exe "%~dp0ocr_reader\start_reader.vbs"

echo.
echo Setup complete. The reader is running quietly in the background and
echo will speak as soon as it detects Mortal Kombat X. Just launch the game
echo normally through Steam.
echo.
echo To remove the automatic startup later, run uninstall.bat.
pause
