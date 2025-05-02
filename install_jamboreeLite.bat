@echo off
REM ==============================================================
REM  JAMboreeLite Windows bootstrap        (tested on Win10/11)
REM  • Installs Git & Python‑3.11 via Chocolatey (if missing)
REM  • Clones/updates the repo to  %USERPROFILE%\JAMboreeLite
REM  • Creates a venv + pip‑installs deps (Flask, pyserial…)
REM  • Adds a desktop shortcut  (python ‑m jamboree.app)
REM  • Optional Task‑Scheduler entry for auto‑start at logon
REM ==============================================================

SET "REPO=https://github.com/askjake/JAMboreeLite.git"
SET "INSTALL_DIR=%USERPROFILE%\JAMboreeLite"
SET "VENV_DIR=%INSTALL_DIR%\venv"

echo ----------------------------------------
echo  JAMboreeLite installer for Windows
echo ----------------------------------------

:: ----------------------------------------------------------------
:: 1 · ensure Chocolatey
:: ----------------------------------------------------------------
where choco >nul 2>&1
IF ERRORLEVEL 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
   "Set-ExecutionPolicy Bypass -Scope Process -Force; ^
    [Net.ServicePointManager]::SecurityProtocol = 3072; ^
    iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))"
)

:: ----------------------------------------------------------------
:: 2 · install Git & Python 3.11 if absent
:: ----------------------------------------------------------------
where git >nul 2>&1 || choco install -y git
:: test for py 3.11 (py launcher preferred)
py -3.11 -c "import sys;print(sys.version)" 2>nul || choco install -y python --version 3.11.0

FOR /F "delims=" %%P IN ('py -3.11 -c "import sys, pathlib;print(pathlib.Path(sys.executable))"') DO SET "PYTHON=%%P"
echo Using Python: %PYTHON%

:: ----------------------------------------------------------------
:: 3 · clone / pull repo
:: ----------------------------------------------------------------
IF EXIST "%INSTALL_DIR%\.git" (
  git -C "%INSTALL_DIR%" pull --ff-only
) ELSE (
  git clone "%REPO%" "%INSTALL_DIR%"
)

:: ----------------------------------------------------------------
:: 4 · venv + deps  (no packaging needed)
:: ----------------------------------------------------------------
%PYTHON% -m venv "%VENV_DIR%"
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV_DIR%\Scripts\pip.exe" install flask pyserial paramiko requests

:: ----------------------------------------------------------------
:: 5 · desktop shortcut (PowerShell COM)
:: ----------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$lnk   = [IO.Path]::Combine([Environment]::GetFolderPath('Desktop'),'JAMboreeLite.lnk'); ^
  $w     = New-Object -ComObject WScript.Shell; ^
  $s     = $w.CreateShortcut($lnk); ^
  $s.TargetPath = '%VENV_DIR:\=\\%\\Scripts\\python.exe'; ^
  $s.Arguments  = '-m jamboree.app'; ^
  $s.WorkingDirectory = '%INSTALL_DIR:\=\\%'; ^
  $s.IconLocation = '%SystemRoot%\\System32\\shell32.dll,175'; ^
  $s.Save()"
echo ✓ Desktop shortcut created.

:: ----------------------------------------------------------------
:: 6 · optional auto‑start (Task Scheduler)
:: ----------------------------------------------------------------
choice /M "Add JAMboreeLite to start automatically at logon?" /C YN
IF ERRORLEVEL 2 GOTO :done

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$act  = New-ScheduledTaskAction  -Execute '%VENV_DIR:\=\\%\\Scripts\\python.exe' -Argument '-m jamboree.app'; ^
  $trig = New-ScheduledTaskTrigger -AtLogOn; ^
  Register-ScheduledTask -TaskName 'JAMboreeLite' -Action $act -Trigger $trig -RunLevel Highest -Force -Description 'Start JAMboree Lite headless Flask';"
echo ✓ Startup task registered.

:done
echo ----------------------------------------
echo Install complete – double‑click the shortcut or run:
echo   \"%VENV_DIR%\Scripts\python.exe\" -m jamboree.app
pause
