@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto dependencies
where py >nul 2>nul
if errorlevel 1 goto python
py -3.14 -m venv .venv
if errorlevel 1 goto fail
goto dependencies
:python
python -m venv .venv
if errorlevel 1 goto fail
:dependencies
if exist "vendor\pypdf\__init__.py" goto offline
if /i "%~1"=="online" goto online
echo Offline source vendor/pypdf is missing.
echo For online setup, explicitly run: setup.bat online
goto fail
:online
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
goto check
:offline
echo Using source-only vendor/pypdf. No network access.
:check
".venv\Scripts\python.exe" -B -c "import sys; sys.path.insert(0, 'vendor'); import tkinter, pypdf; assert pypdf.__version__ == '6.20.1', pypdf.__version__; print('Setup OK: Python', sys.version.split()[0], '/ pypdf', pypdf.__version__)"
if errorlevel 1 goto fail
echo Double-click start.bat to launch.
pause
exit /b 0
:fail
echo Setup failed. See README.md.
pause
exit /b 1
