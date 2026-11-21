@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" goto run
echo First run: setting up MudPilot (one time, about a minute)...
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m venv .venv) else (python -m venv .venv)
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Python 3.10 or newer is required. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup, then run this again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
  echo Package install failed - check your internet connection and run again.
  pause
  exit /b 1
)
:run
rem Desktop shortcut with the MudPilot logo (made once; delete it if you don't want it)
if not exist ".shortcut_made" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'MudPilot.lnk')); $s.TargetPath='%~dp0.venv\Scripts\pythonw.exe'; $s.Arguments='-m mudpilot.launcher'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0mudpilot\assets\mudpilot.ico'; $s.Description='MudPilot'; $s.Save()" >nul 2>nul
  echo done> ".shortcut_made"
)
rem MudPilot.bat --data PVE  opens a second character set (its own settings in data-PVE\) from this same install
start "" ".venv\Scripts\pythonw.exe" -m mudpilot.launcher %*
