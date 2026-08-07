@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem JAMboreeLite installer for Windows 10/11.
rem This file is intentionally linear: no CALL, GOTO, or batch labels.
rem That keeps it compatible with LF-only files from GitHub ZIP downloads.
rem
rem Update policy:
rem   * When run from a separate source tree/ZIP, that exact source is installed.
rem   * When run from the live install directory, update_jamboreeLite.cmd stages
rem     a clean requested Git ref first, then invokes this installer from there.
rem   * base.txt and the venv are preserved.
rem   * existing application source is backed up before an update unless
rem     JAMBOREE_SKIP_CODE_BACKUP=1 is set.

set "REPO=https://github.com/askjake/JAMboreeLite.git"
set "REF=main"
if defined JAMBOREE_REF set "REF=%JAMBOREE_REF%"

set "SOURCE=%~dp0"
for %%I in ("%SOURCE%.") do set "SOURCE=%%~fI"

set "INSTALL=%USERPROFILE%\Documents\JAMboreeLite"
if defined JAMBOREE_INSTALL_DIR set "INSTALL=%JAMBOREE_INSTALL_DIR%"
for %%I in ("%INSTALL%") do set "INSTALL=%%~fI"

rem Never overwrite the batch file that is currently executing. Delegate an
rem in-place update to a clean staged copy instead.
if /I "%SOURCE%"=="%INSTALL%" (
    if exist "%SOURCE%\update_jamboreeLite.cmd" (
        echo Installed-tree execution detected; staging a clean update first.
        cmd.exe /d /c ""%SOURCE%\update_jamboreeLite.cmd""
        set "DELEGATE_RC=!ERRORLEVEL!"
        exit /b !DELEGATE_RC!
    )
    echo ERROR: In-place update requires update_jamboreeLite.cmd.
    echo Run this installer from an extracted/cloned source tree instead.
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

set "VENV=%INSTALL%\venv"
set "VPY=%VENV%\Scripts\python.exe"
set "PY="
set "SOURCE_COMMIT=%JAMBOREE_SOURCE_COMMIT%"
set "SOURCE_REF=%JAMBOREE_SOURCE_REF%"
if not defined SOURCE_REF set "SOURCE_REF=%REF%"

echo.
echo ============================================================
echo JAMboreeLite installer
echo ============================================================
echo Source : "%SOURCE%"
echo Install: "%INSTALL%"
echo Ref    : "%SOURCE_REF%"
echo.

rem Locate Python 3.11 or newer.
for /f "delims=" %%P in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do if not defined PY set "PY=%%P"

if not defined PY (
    where python.exe >nul 2>&1
    if not errorlevel 1 (
        python.exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY=python.exe"
    )
)

if not defined PY (
    where python3.exe >nul 2>&1
    if not errorlevel 1 (
        python3.exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY=python3.exe"
    )
)

if not defined PY (
    echo ERROR: Python 3.11 or newer was not found.
    echo Install Python 3.11+ and enable either the Python launcher or PATH entry.
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

echo Using Python: "!PY!"
"!PY!" -c "import sys; print('Python', sys.version.split()[0])"
if errorlevel 1 (
    echo ERROR: The selected Python interpreter could not be started.
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

if not exist "%SOURCE%\jamboree\app.py" (
    echo ERROR: The selected source does not contain jamboree\app.py.
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

rem Resolve a source commit fingerprint when the source is a Git checkout.
if not defined SOURCE_COMMIT (
    where git.exe >nul 2>&1
    if not errorlevel 1 if exist "%SOURCE%\.git" (
        for /f "delims=" %%C in ('git.exe -C "%SOURCE%" rev-parse HEAD 2^>nul') do if not defined SOURCE_COMMIT set "SOURCE_COMMIT=%%C"
    )
)
if not defined SOURCE_COMMIT set "SOURCE_COMMIT=unknown"

echo Source commit: !SOURCE_COMMIT!

echo.
echo === Installing or updating application files ===

if not exist "%INSTALL%" mkdir "%INSTALL%"
if not exist "%INSTALL%" (
    echo ERROR: Could not create "%INSTALL%".
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

rem Preserve the previous code/config tree before replacing runtime source.
if exist "%INSTALL%\jamboree\app.py" if /I not "!JAMBOREE_SKIP_CODE_BACKUP!"=="1" (
    set "BACKUP_ROOT=%LOCALAPPDATA%\JAMboreeLite\update-backups\backup_!RANDOM!_!RANDOM!"
    if not defined LOCALAPPDATA set "BACKUP_ROOT=%TEMP%\JAMboreeLite_update_backup_!RANDOM!_!RANDOM!"
    mkdir "!BACKUP_ROOT!" >nul 2>&1
    echo Backing up current application tree to:
    echo   !BACKUP_ROOT!
    robocopy "%INSTALL%" "!BACKUP_ROOT!" /E /COPY:DAT /R:1 /W:1 /XD ".git" "venv" ".venv" "__pycache__" /XF "base.txt.lock" "*.pyc" >nul
    set "BACKUP_RC=!ERRORLEVEL!"
    if !BACKUP_RC! GEQ 8 (
        echo ERROR: Could not create pre-update backup. Update aborted.
        if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
        exit /b 1
    )
)

rem Mirror the runtime package so removed modules cannot linger from an older
rem release. Runtime state lives outside this directory and is not mirrored.
robocopy "%SOURCE%\jamboree" "%INSTALL%\jamboree" /MIR /COPY:DAT /R:2 /W:1 /XD "__pycache__" /XF "*.pyc"
set "ROBOCOPY_RC=!ERRORLEVEL!"
if !ROBOCOPY_RC! GEQ 8 (
    echo ERROR: jamboree runtime sync failed with exit code !ROBOCOPY_RC!.
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

if exist "%SOURCE%\tests" (
    robocopy "%SOURCE%\tests" "%INSTALL%\tests" /MIR /COPY:DAT /R:2 /W:1 /XD "__pycache__" /XF "*.pyc"
    set "ROBOCOPY_RC=!ERRORLEVEL!"
    if !ROBOCOPY_RC! GEQ 8 (
        echo ERROR: tests sync failed with exit code !ROBOCOPY_RC!.
        if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
        exit /b 1
    )
)

if exist "%SOURCE%\DART_16Remotes_Buffered_Handshake_TxAck_Timestamps" (
    robocopy "%SOURCE%\DART_16Remotes_Buffered_Handshake_TxAck_Timestamps" "%INSTALL%\DART_16Remotes_Buffered_Handshake_TxAck_Timestamps" /MIR /COPY:DAT /R:2 /W:1
    set "ROBOCOPY_RC=!ERRORLEVEL!"
    if !ROBOCOPY_RC! GEQ 8 (
        echo ERROR: DART source sync failed with exit code !ROBOCOPY_RC!.
        if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
        exit /b 1
    )
)

rem Copy the remaining top-level/support files while protecting runtime state.
robocopy "%SOURCE%" "%INSTALL%" /E /COPY:DAT /R:2 /W:1 /XD ".git" ".github" ".agent_payload" "venv" ".venv" "__pycache__" "jamboree" "tests" "DART_16Remotes_Buffered_Handshake_TxAck_Timestamps" /XF "base.txt" "base.txt.bak" "base.txt.backup" "base.txt.lock" "*.pyc"
set "ROBOCOPY_RC=!ERRORLEVEL!"
if !ROBOCOPY_RC! GEQ 8 (
    echo ERROR: support-file sync failed with exit code !ROBOCOPY_RC!.
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

if not exist "%INSTALL%\jamboree\app.py" (
    echo ERROR: "%INSTALL%\jamboree\app.py" was not installed.
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

if not exist "%INSTALL%\base.txt" (
    >"%INSTALL%\base.txt" echo {"stbs": {}}
    if errorlevel 1 (
        echo ERROR: Could not create "%INSTALL%\base.txt".
        if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
        exit /b 1
    )
    echo Created a new empty base.txt.
) else (
    echo Preserved existing base.txt.
)

>"%INSTALL%\.jamboree_source_commit" echo !SOURCE_COMMIT!
>"%INSTALL%\.jamboree_source_ref" echo !SOURCE_REF!

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
            if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
            exit /b 1
        )
    )
)

if not exist "%VPY%" (
    "!PY!" -m venv "%VENV%"
    if errorlevel 1 (
        echo ERROR: Failed to create the virtual environment.
        if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
        exit /b 1
    )
)

if not exist "%VPY%" (
    echo ERROR: Virtual-environment Python was not created.
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

echo.
echo === Installing Python dependencies ===
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip.
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

if exist "%INSTALL%\requirements_new.txt" (
    "%VPY%" -m pip install -r "%INSTALL%\requirements_new.txt"
) else (
    "%VPY%" -m pip install "flask>=3.0,<4" "keyring>=24.2,<26" "numpy>=1.26,<3" "opencv-python-headless>=4.9,<6" "paramiko>=3.4,<6" "Pillow>=10,<13" "pytesseract>=0.3.10,<0.4" "pyserial>=3.5,<4" "requests>=2.31,<3"
)
if errorlevel 1 (
    echo ERROR: Dependency installation failed.
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

echo.
echo === Verifying installed application ===
pushd "%INSTALL%" >nul
"%VPY%" -c "import jamboree.app; print('JAMboreeLite import check passed')"
set "VERIFY_RC=!ERRORLEVEL!"
if "!VERIFY_RC!"=="0" (
    "%VPY%" -c "from pathlib import Path; root=Path('.'); print('Installed ref:', root.joinpath('.jamboree_source_ref').read_text().strip()); print('Installed commit:', root.joinpath('.jamboree_source_commit').read_text().strip())"
    set "VERIFY_RC=!ERRORLEVEL!"
)
popd >nul
if not "!VERIFY_RC!"=="0" (
    echo ERROR: JAMboreeLite failed its import/fingerprint smoke test.
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

where tesseract.exe >nul 2>&1
if errorlevel 1 (
    echo.
    echo WARNING: tesseract.exe was not found on PATH.
    echo Normal SGS and DART controls will work, but OCR-based IP/PIN recovery
    echo requires the Tesseract OCR application.
)

if /I not "!JAMBOREE_SKIP_SHORTCUTS!"=="1" (
    echo.
    echo === Creating shortcuts ===
    powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $ws=New-Object -ComObject WScript.Shell; $desktop=[Environment]::GetFolderPath('Desktop'); $lnk=$ws.CreateShortcut((Join-Path $desktop 'JAMboreeLite.lnk')); $lnk.TargetPath='%VPY%'; $lnk.Arguments='-m jamboree.app'; $lnk.WorkingDirectory='%INSTALL%'; $lnk.IconLocation='%SystemRoot%\System32\shell32.dll,175'; $lnk.Save()"
    if errorlevel 1 (
        echo WARNING: Desktop shortcut creation failed.
    ) else (
        echo Desktop shortcut created.
    )

    if /I not "!JAMBOREE_SKIP_STARTUP!"=="1" (
        powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $ws=New-Object -ComObject WScript.Shell; $startup=[Environment]::GetFolderPath('Startup'); $lnk=$ws.CreateShortcut((Join-Path $startup 'JAMboreeLite.lnk')); $lnk.TargetPath='%VPY%'; $lnk.Arguments='-m jamboree.app'; $lnk.WorkingDirectory='%INSTALL%'; $lnk.IconLocation='%SystemRoot%\System32\shell32.dll,175'; $lnk.Save()"
        if errorlevel 1 (
            echo WARNING: Startup shortcut creation failed. JAMboreeLite was still installed.
        ) else (
            echo Per-user startup shortcut created.
        )
    )
)

echo.
echo ============================================================
echo Installation/update completed successfully.
echo ============================================================
echo Ref   : !SOURCE_REF!
echo Commit: !SOURCE_COMMIT!
echo Run:
echo   cd /d "%INSTALL%"
echo   "%VPY%" -m jamboree.app
echo.
echo Browser:
echo   http://localhost:5003/
echo   http://localhost:5003/settops

if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
exit /b 0
