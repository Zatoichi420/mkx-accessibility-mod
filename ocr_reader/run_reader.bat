@echo off
cd /d "%~dp0"

REM Try the standard Windows Python Launcher first (present on most Python
REM installs regardless of user/machine), then "python" on PATH, then this
REM machine's own known install path as a last resort - in that order so
REM this script isn't tied to one specific user's setup.
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set "PYEXE=py -3"
    goto :run
)
where python >nul 2>&1
if %ERRORLEVEL%==0 (
    set "PYEXE=python"
    goto :run
)
set "PYEXE=C:\Users\vegas\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\python.exe"
echo [run_reader.bat] No "py"/"python" on PATH, falling back to a hardcoded path. >> "%~dp0reader_log.txt"

:run
%PYEXE% -u "%~dp0main.py" >> "%~dp0reader_log.txt" 2>&1
