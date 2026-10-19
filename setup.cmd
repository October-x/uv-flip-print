@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Ready. Run start.cmd to open the workbench.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.12 or check the network, then retry.
pause
exit /b 1
