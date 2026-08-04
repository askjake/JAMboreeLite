@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem JAMboreeLite installer for Windows 10/11.
rem This installer prefers the source tree containing this file. Git is only
rem required when the installer is launched without the rest of the repository.

set "REPO=https://github.com/askjake/JAMboreeLite.git"
set "REF=main"
if defined JAMBOREE_REF set "REF=%JAMBOREE_REF%"

set "SOURCE=%~dp0"
for %%I in ("%SOURCE%.") do set "SOURCE=%%~fI"

set "INSTALL=%USERPROFILE%\Documents\JAMboreeLite"
if defined JAMBOREE_INSTALL_DIR set "INSTALL=%JAMBOREE_INSTALL_DIR%"
for %%I in ("%INSTALL%") do set "INSTALL=%%~fI"

set "VENV=%INSTALL%\venv"
set "PY="
set "VPY=%VENV%\Scripts\python.exe"
set "FAILED=0"

echo.
echo ============================================================
echo JAMboreeLite installer
echo ============================================================
echo Source : "%SOURCE%"
echo Install: "%INSTALL%"
echo.

call :find_python
if errorlevel 1 goto :fatal

echo Using Python: "%PY%"
"%PY%" -c "import sys; print('Python', sys.version.split()[0])"
if errorlevel 1 (
    echo ERROR: The selected Python interpreter could not be started.
    goto :fatal
)

echo.
echo === Installing or updating application files ===
if exist "%SOURCE%\jamboree\app.py" (
    call :copy_local_source
    if errorlevel 1 goto :fatal
) else (
    call :clone_source
    if errorlevel 1 goto :fatal
)

if not exist "%INSTALL%\jamboree\app.py" (
    echo ERROR: "%INSTALL%\jamboree\app.py" was not installed.
    goto :fatal
)

if not exist "%INSTALL%\base.txt" (
    >"%INSTALL%\base.txt" echo {"stbs": {}}
    if errorlevel 1 (
        echo ERROR: Could not create "%INSTALL%\base.txt".
        goto :fatal
    )
    echo Created a new empty base.txt.
) else (
    echo Preserved existing base.txt.
)

echo.
echo === Creating virtual environment ===
if exist "%VPY%" (
    "%VPY%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo Existing virtual environment uses an unsupported Python version.
        echo Recreating "%VENV%".
        rmdir /S /Q "%VENV%"
        if exist "%VENV%" (
            echo ERROR: Could not remove the old virtual environment.
            goto :fatal
        )
    )
)

if not exist "%VPY%" (
    "%PY%" -m venv "%VENV%"
    if errorlevel 1 (
        echo ERROR: Failed to create the virtual environment.
        goto :fatal
    )
)

if not exist "%VPY%" (
    echo ERROR: Virtual-environment Python was not created.
    goto :fatal
)

echo.
echo === Installing Python dependencies ===
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip.
    goto :fatal
)

"%VPY%" -m pip install ^
    "flask>=3.0,<4" ^
    "keyring>=24.2,<26" ^
    "numpy>=1.26,<3" ^
    "opencv-python-headless>=4.9,<6" ^
    "paramiko>=3.4,<6" ^
    "Pillow>=10,<13" ^
    "pytesseract>=0.3.10,<0.4" ^
    "pyserial>=3.5,<4" ^
    "requests>=2.31,<3"
if errorlevel 1 (
    echo ERROR: Dependency installation failed.
    goto :fatal
)

echo.
echo === Verifying installed application ===
pushd "%INSTALL%" >nul
"%VPY%" -c "import jamboree.app; print('JAMboreeLite import check passed')"
set "VERIFY_RC=!ERRORLEVEL!"
popd >nul
if not "!VERIFY_RC!"=="0" (
    echo ERROR: JAMboreeLite failed its import smoke test.
    goto :fatal
)

where tesseract.exe >nul 2>&1
if errorlevel 1 (
    echo.
    echo WARNING: tesseract.exe was not found on PATH.
    echo The normal SGS and DART controls will work, but OCR-based IP/PIN
    echo recovery requires the Tesseract OCR application.
)

if /I not "%JAMBOREE_SKIP_SHORTCUTS%"=="1" (
    call :create_shortcuts
)

echo.
echo ============================================================
echo Installation completed successfully.
echo ============================================================
echo Run:
echo   cd /d "%INSTALL%"
echo   "%VPY%" -m jamboree.app
echo.
echo Browser:
echo   http://localhost:5003/
echo   http://localhost:5003/settops
goto :success

:find_python
for /f "delims=" %%P in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%P"
if defined PY exit /b 0

where python.exe >nul 2>&1
if not errorlevel 1 (
    python.exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PY=python.exe"
        exit /b 0
    )
)

where python3.exe >nul 2>&1
if not errorlevel 1 (
    python3.exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PY=python3.exe"
        exit /b 0
    )
)

echo ERROR: Python 3.11 or newer was not found.
echo Install Python 3.11+ and enable either the Python launcher or PATH entry.
exit /b 1

:copy_local_source
if /I "%SOURCE%"=="%INSTALL%" (
    echo Installer is running from the installation directory; no source copy is needed.
    exit /b 0
)

if not exist "%INSTALL%" (
    mkdir "%INSTALL%"
    if errorlevel 1 (
        echo ERROR: Could not create "%INSTALL%".
        exit /b 1
    )
)

echo Installing from the downloaded/local source tree.
robocopy "%SOURCE%" "%INSTALL%" /E /COPY:DAT /R:2 /W:1 ^
    /XD ".git" ".github" ".agent_payload" "venv" ".venv" "__pycache__" ^
    /XF "base.txt" "base.txt.bak" "base.txt.backup" "base.txt.lock" "*.pyc"
set "ROBOCOPY_RC=!ERRORLEVEL!"
if !ROBOCOPY_RC! GEQ 8 (
    echo ERROR: robocopy failed with exit code !ROBOCOPY_RC!.
    exit /b 1
)
exit /b 0

:clone_source
set "GIT="
for /f "delims=" %%G in ('where git.exe 2^>nul') do if not defined GIT set "GIT=%%G"
if not defined GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined GIT if exist "%ProgramFiles(x86)%\Git\cmd\git.exe" set "GIT=%ProgramFiles(x86)%\Git\cmd\git.exe"
if not defined GIT if exist "%ProgramData%\chocolatey\bin\git.exe" set "GIT=%ProgramData%\chocolatey\bin\git.exe"

if not defined GIT (
    echo ERROR: This installer was launched without the repository source,
    echo and Git was not found.
    echo.
    echo Either:
    echo   1. Run install_jamboreeLite.cmd from an extracted JAMboreeLite ZIP, or
    echo   2. Install Git for Windows and rerun this installer.
    exit /b 1
)

set "TMP=%TEMP%\JAMboreeLite_clone_%RANDOM%_%RANDOM%"
if exist "%TMP%" rmdir /S /Q "%TMP%"

echo Cloning %REPO% branch %REF%.
"%GIT%" clone --depth 1 --branch "%REF%" "%REPO%" "%TMP%"
if errorlevel 1 (
    echo ERROR: Git clone failed.
    if exist "%TMP%" rmdir /S /Q "%TMP%"
    exit /b 1
)

if not exist "%TMP%\jamboree\app.py" (
    echo ERROR: The cloned repository does not contain jamboree\app.py.
    rmdir /S /Q "%TMP%"
    exit /b 1
)

if not exist "%INSTALL%" mkdir "%INSTALL%"
robocopy "%TMP%" "%INSTALL%" /E /COPY:DAT /R:2 /W:1 ^
    /XD ".git" ".github" ".agent_payload" "venv" ".venv" "__pycache__" ^
    /XF "base.txt" "base.txt.bak" "base.txt.backup" "base.txt.lock" "*.pyc"
set "ROBOCOPY_RC=!ERRORLEVEL!"
rmdir /S /Q "%TMP%"

if !ROBOCOPY_RC! GEQ 8 (
    echo ERROR: robocopy failed with exit code !ROBOCOPY_RC!.
    exit /b 1
)
exit /b 0

:create_shortcuts
echo.
echo === Creating shortcuts ===
powershell -NoProfile -Command ^
    "$ErrorActionPreference='Stop';" ^
    "$ws=New-Object -ComObject WScript.Shell;" ^
    "$desktop=[Environment]::GetFolderPath('Desktop');" ^
    "$lnk=$ws.CreateShortcut((Join-Path $desktop 'JAMboreeLite.lnk'));" ^
    "$lnk.TargetPath='%VPY%';" ^
    "$lnk.Arguments='-m jamboree.app';" ^
    "$lnk.WorkingDirectory='%INSTALL%';" ^
    "$lnk.IconLocation='%SystemRoot%\System32\shell32.dll,175';" ^
    "$lnk.Save()"
if errorlevel 1 (
    echo WARNING: Desktop shortcut creation failed.
) else (
    echo Desktop shortcut created.
)

if /I "%JAMBOREE_SKIP_STARTUP%"=="1" exit /b 0

powershell -NoProfile -Command ^
    "$ErrorActionPreference='Stop';" ^
    "$ws=New-Object -ComObject WScript.Shell;" ^
    "$startup=[Environment]::GetFolderPath('Startup');" ^
    "$lnk=$ws.CreateShortcut((Join-Path $startup 'JAMboreeLite.lnk'));" ^
    "$lnk.TargetPath='%VPY%';" ^
    "$lnk.Arguments='-m jamboree.app';" ^
    "$lnk.WorkingDirectory='%INSTALL%';" ^
    "$lnk.IconLocation='%SystemRoot%\System32\shell32.dll,175';" ^
    "$lnk.Save()"
if errorlevel 1 (
    echo WARNING: Startup shortcut creation failed. JAMboreeLite was still installed.
) else (
    echo Per-user startup shortcut created.
)
exit /b 0

:fatal
echo.
echo ============================================================
echo INSTALLATION FAILED.
echo Review the first ERROR message above. No success was reported.
echo ============================================================
set "FAILED=1"
goto :finish

:success
set "FAILED=0"

:finish
if /I not "%JAMBOREE_NO_PAUSE%"=="1" pause
endlocal & exit /b %FAILED%
