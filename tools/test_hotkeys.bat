@echo off
REM Double-click this file yourself (don't have it launched for you) -
REM GetAsyncKeyState-based hotkey detection only works for a process you
REM start directly. See PROGRESS.md's "Important operational finding".
cd /d "%~dp0"
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py -3 test_hotkeys.py
    goto :end
)
where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python test_hotkeys.py
    goto :end
)
"C:\Users\vegas\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\python.exe" test_hotkeys.py
:end
pause
