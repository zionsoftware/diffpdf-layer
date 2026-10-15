@echo off
setlocal
cd /d "%~dp0"
call "%~dp0tools\run_python.bat" "%~dp0main.py" %*
set "RESULT=%ERRORLEVEL%"
if not "%~1"=="" exit /b %RESULT%
if not "%RESULT%"=="0" pause
exit /b %RESULT%
