@echo off
setlocal
if defined DIFFPDF_PYTHON goto explicit
py -3.14 -B -S -c "import sys; assert sys.prefix == sys.base_prefix" >nul 2>nul
if not errorlevel 1 goto launcher
python -B -S -c "import sys; assert sys.prefix == sys.base_prefix; assert sys.version_info[:2] == (3, 14)" >nul 2>nul
if not errorlevel 1 goto python
goto missing
:explicit
"%DIFFPDF_PYTHON%" -B -S -c "import sys; assert sys.prefix == sys.base_prefix; assert sys.version_info[:2] == (3, 14)" >nul 2>nul
if errorlevel 1 goto missing
"%DIFFPDF_PYTHON%" -B -S %*
exit /b %ERRORLEVEL%
:launcher
py -3.14 -B -S %*
exit /b %ERRORLEVEL%
:python
python -B -S %*
exit /b %ERRORLEVEL%
:missing
echo Python 3.14 outside a virtual environment was not found.
echo Install Python with Tcl/Tk, or set DIFFPDF_PYTHON to its full executable path.
echo See README.md. No packages or environments have been installed.
exit /b 2
