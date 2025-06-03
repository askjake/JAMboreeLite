@echo off
REM JAMboreeLite CMD installer  (Win10/11 x64)

setlocal

set "REPO=https://github.com/askjake/JAMboreeLite.git"
set "INSTALL=%USERPROFILE%\Documents\JAMboreeLite"
set "VENV=%INSTALL%\venv"

echo === Checking prerequisites ===
where choco >nul 2>&1 || (
  echo Installing Chocolatey…
  powershell -NoProfile -ExecutionPolicy Bypass ^
    -Command "Set-ExecutionPolicy Bypass -Scope Process -Force; [Net.ServicePointManager]::SecurityProtocol = 3072; iex (New-Object Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1')"
  call refreshenv
)

where git  >nul 2>&1 || choco install -y git

echo.
echo === Locating a Python 3.11 interpreter ===
REM 1) First try “py -3.11”
for /f "delims=" %%P in ('py -3.11 -c "import sys, pathlib; print(pathlib.Path(sys.executable))" 2^>nul') do set "PY=%%P"
if defined PY goto :foundPython

REM 2) Next try “python --version” and require 3.x
where python >nul 2>&1 && (
  for /f "tokens=2 delims= " %%V in ('python --version 2^>^&1') do (
    for /f "tokens=1,2 delims=." %%A in ("%%V") do (
      if "%%A"=="3" set "PY=python"
    )
  )
)
if defined PY goto :foundPython

REM 3) Next try “python3 --version” and require 3.x
where python3 >nul 2>&1 && (
  for /f "tokens=2 delims= " %%V in ('python3 --version 2^>^&1') do (
    for /f "tokens=1,2 delims=." %%A in ("%%V") do (
      if "%%A"=="3" set "PY=python3"
    )
  )
)
if defined PY goto :foundPython

echo.
echo ERROR: No suitable Python 3 interpreter found.
echo Please install Python 3.11 (or any Python 3), and make sure “py -3.11” or “python” is on your PATH.
exit /b 1

:foundPython
echo Using Python: %PY%
echo.

REM ── Now proceed exactly as before ──

echo === Clone / update repo ===
set "TMP=%TEMP%\JAMboreeLite_clone"
if not exist "%INSTALL%" (
  echo First-time install: cloning into "%INSTALL%"…
  git clone "%REPO%" "%INSTALL%"
) else (
  echo Updating existing install…
  if exist "%TMP%" (
    rmdir /S /Q "%TMP%"
  )
  echo → cloning to temp dir…
  git clone "%REPO%" "%TMP%"
  echo → copying only newer files into "%INSTALL%"…
  robocopy "%TMP%" "%INSTALL%" /E /XO /COPY:DAT /R:1 /W:1
  echo → cleaning up temp…
  rmdir /S /Q "%TMP%"
)

echo.
echo === Creating virtual-env and installing dependencies ===
"%PY%" -m venv "%VENV%"
"%VENV%\Scripts\pip.exe" install --upgrade pip
"%VENV%\Scripts\pip.exe" install flask pyserial paramiko requests

echo.
echo === Desktop shortcut ===
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; $desktop = [IO.Path]::Combine($env:USERPROFILE,'Desktop'); $lnkPath = [IO.Path]::Combine($desktop,'JAMboreeLite.lnk'); $s = $ws.CreateShortcut($lnkPath); $s.TargetPath = '%VENV%\Scripts\python.exe'; $s.Arguments = '-m jamboree.app'; $s.WorkingDirectory = '%INSTALL%'; $s.IconLocation = '%SystemRoot%\System32\shell32.dll,175'; $s.Save()"

if errorlevel 2 goto done

echo.
echo === Registering startup task ===
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$act = New-ScheduledTaskAction -Execute '%VENV%\Scripts\python.exe' -Argument '-m jamboree.app'; $tr = New-ScheduledTaskTrigger -AtLogOn; Register-ScheduledTask -TaskName 'JAMboreeLite' -Action $act -Trigger $tr -RunLevel Highest -Force -Description 'Start JAMboree headless Flask'"

echo ✓ Startup task registered.

:done
echo.
echo Installation complete – double-click the desktop icon or run:
echo   "%VENV%\Scripts\python.exe" -m jamboree.app
pause
endlocal
exit /b 0
