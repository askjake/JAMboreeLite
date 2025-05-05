@echo off
REM JAMboreeLite CMD installer  (Win10/11 x64)

set "REPO=https://github.com/askjake/JAMboreeLite.git"
set "INSTALL=%USERPROFILE%\Documents\JAMboreeLite"
set "VENV=%INSTALL%\venv"

echo === Checking prerequisites ===
where choco >nul 2>&1 || (
  echo Installing Chocolatey…
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy Bypass -Scope Process -Force; [Net.ServicePointManager]::SecurityProtocol=3072; iex ((New-Object Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))"
  call refreshenv
)

where git  >nul 2>&1 || choco install -y git
py -3.11 -c "exit()" 2>nul || (
  echo "Python 3.11 unavailable, falling back to system default"
  for /f "delims=" %%P in ('py -0p ^| findstr /R "^ *[23]\.[0-9][0-9]*\.[0-9] "') do set "PY=%%P"
  goto :skip_pyinstall
)
:skip_pyinstall

for /f "delims=" %%P in ('py -3.11 -c "import sys, pathlib;print(pathlib.Path(sys.executable))"') do set "PY=%%P"
echo Using Python: %PY%

echo === Clone / update repo ===
if exist "%INSTALL%\.git" (git -C "%INSTALL%" pull --ff-only) else git clone "%REPO%" "%INSTALL%"

echo === Virtual‑env + deps ===
%PY% -m venv "%VENV%"
"%VENV%\Scripts\pip.exe" install --upgrade pip
"%VENV%\Scripts\pip.exe" install flask pyserial paramiko requests

echo === Desktop shortcut ===
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell;$s=$ws.CreateShortcut([IO.Path]::Combine($env:USERPROFILE,'Desktop','JAMboreeLite.lnk'));$s.TargetPath='%VENV:\=\\%\\Scripts\\python.exe';$s.Arguments='-m jamboree.app';$s.WorkingDirectory='%INSTALL:\=\\%';$s.IconLocation='%SystemRoot%\\System32\\shell32.dll,175';$s.Save()"


echo.
choice /M "Add JAMboreeLite to start automatically at logon?" /C YN
if errorlevel 2 goto done

powershell -NoProfile -ExecutionPolicy Bypass -Command "$act=New-ScheduledTaskAction -Execute '%VENV:\=\\%\\Scripts\\python.exe' -Argument '-m jamboree.app';$tr=New-ScheduledTaskTrigger -AtLogOn;Register-ScheduledTask -TaskName 'JAMboreeLite' -Action $act -Trigger $tr -RunLevel Highest -Force -Description 'Start JAMboree headless Flask'"

echo ✓ Startup task registered.
:done
echo.
echo Installation complete – double‑click the desktop icon or run:
echo   "%VENV%\Scripts\python.exe" -m jamboree.app
pause
