@echo off
cd /d "%~dp0"
set "PYEXE=C:\Users\vegas\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\python.exe"
if not exist "%PYEXE%" (
    echo [run_reader.bat] Configured Python path not found, falling back to "python" on PATH. >> "%~dp0reader_log.txt"
    set "PYEXE=python"
)
"%PYEXE%" -u "%~dp0main.py" >> "%~dp0reader_log.txt" 2>&1
