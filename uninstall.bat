@echo off
REM Removes the Startup-folder shortcut created by install.bat. Does not
REM touch known_screens/ or any of your captured data.
setlocal

for /f "usebackq delims=" %%S in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Startup')"`) do set "STARTUP_DIR=%%S"
set "SHORTCUT=%STARTUP_DIR%\MKX Accessibility Reader.lnk"

if exist "%SHORTCUT%" (
    del "%SHORTCUT%"
    echo Removed the Startup shortcut. The reader will no longer start automatically at login.
) else (
    echo No Startup shortcut was found ^(already removed, or never installed^).
)
echo.
echo You can still run it manually via ocr_reader\run_reader.bat any time.
echo ^(If a copy is already running from this session, it'll keep running
echo quietly until you close it or log off - this only stops future
echo auto-starts.^)
pause
