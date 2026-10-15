@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" goto run
echo Python virtual environment was not found.
echo Run setup.bat first. See README.md for offline setup.
pause
exit /b 1
:run
"%PYTHON_EXE%" -B -c "import sys; sys.path.insert(0, 'vendor'); import tkinter, pypdf; assert pypdf.__version__ == '6.20.1'" 2>nul
if errorlevel 1 (
    echo Missing tkinter or pypdf. See README.md.
    if not "%~1"=="" exit /b 2
    pause
    exit /b 1
)
"%PYTHON_EXE%" "%~dp0main.py" %*
set "RESULT=%ERRORLEVEL%"
if not "%~1"=="" exit /b %RESULT%
if not "%RESULT%"=="0" pause
exit /b %RESULT%
