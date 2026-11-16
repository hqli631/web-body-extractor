@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>nul
if errorlevel 1 goto pythonfallback
py -3 -m venv .venv
if errorlevel 1 goto failed
goto install
:pythonfallback
python -m venv .venv
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -c "import importlib.metadata; assert importlib.metadata.version('lxml') == '6.1.3'; assert importlib.metadata.version('trafilatura') == '2.3.1'" >nul 2>nul
if not errorlevel 1 goto extract
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
:extract
".venv\Scripts\python.exe" -X utf8 app.py batch
if errorlevel 1 goto failed
start "" "reports\index.html"
echo Completed. Report: reports\index.html
pause
exit /b 0
:failed
echo Failed. Check the error above. Python 3.10 or newer is required.
pause
exit /b 1
