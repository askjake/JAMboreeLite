@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem JAMboreeLite exact-ref updater for Windows 10/11.
rem It stages a clean Git copy outside the live installation, then invokes the
rem normal installer from that clean source. base.txt and the venv are preserved
rem by install_jamboreeLite.cmd.

set "REPO=https://github.com/askjake/JAMboreeLite.git"
set "REF=main"
if defined JAMBOREE_REF set "REF=%JAMBOREE_REF%"

set "INSTALL=%USERPROFILE%\Documents\JAMboreeLite"
if defined JAMBOREE_INSTALL_DIR set "INSTALL=%JAMBOREE_INSTALL_DIR%"
for %%I in ("%INSTALL%") do set "INSTALL=%%~fI"

set "GIT="
for /f "delims=" %%G in ('where git.exe 2^>nul') do if not defined GIT set "GIT=%%G"
if not defined GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined GIT if exist "%ProgramFiles(x86)%\Git\cmd\git.exe" set "GIT=%ProgramFiles(x86)%\Git\cmd\git.exe"
if not defined GIT if exist "%ProgramData%\chocolatey\bin\git.exe" set "GIT=%ProgramData%\chocolatey\bin\git.exe"

if not defined GIT (
    echo ERROR: Git for Windows is required to update JAMboreeLite by ref.
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

set "TMP=%TEMP%\JAMboreeLite_update_%RANDOM%_%RANDOM%"
if exist "!TMP!" rmdir /S /Q "!TMP!"

echo.
echo ============================================================
echo JAMboreeLite updater
echo ============================================================
echo Repository: %REPO%
echo Ref       : %REF%
echo Install   : "%INSTALL%"
echo.

echo === Staging clean source ===
"!GIT!" clone --no-checkout --depth 1 "%REPO%" "!TMP!"
if errorlevel 1 (
    echo ERROR: Could not clone JAMboreeLite.
    if exist "!TMP!" rmdir /S /Q "!TMP!"
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

"!GIT!" -C "!TMP!" fetch --depth 1 origin "%REF%"
if errorlevel 1 (
    echo ERROR: Could not fetch requested ref "%REF%".
    rmdir /S /Q "!TMP!"
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

"!GIT!" -C "!TMP!" checkout --detach FETCH_HEAD
if errorlevel 1 (
    echo ERROR: Could not check out requested ref "%REF%".
    rmdir /S /Q "!TMP!"
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

set "SOURCE_COMMIT="
for /f "delims=" %%C in ('"!GIT!" -C "!TMP!" rev-parse HEAD') do if not defined SOURCE_COMMIT set "SOURCE_COMMIT=%%C"
if not defined SOURCE_COMMIT (
    echo ERROR: Could not resolve staged source commit.
    rmdir /S /Q "!TMP!"
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

echo Staged commit: !SOURCE_COMMIT!

set "JAMBOREE_INSTALL_DIR=%INSTALL%"
set "JAMBOREE_SOURCE_COMMIT=!SOURCE_COMMIT!"
set "JAMBOREE_SOURCE_REF=%REF%"

if not exist "!TMP!\install_jamboreeLite.cmd" (
    echo ERROR: Staged source does not contain install_jamboreeLite.cmd.
    rmdir /S /Q "!TMP!"
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b 1
)

echo.
echo === Applying staged source ===
cmd.exe /d /c ""!TMP!\install_jamboreeLite.cmd""
set "UPDATE_RC=!ERRORLEVEL!"

rmdir /S /Q "!TMP!" >nul 2>&1

if not "!UPDATE_RC!"=="0" (
    echo ERROR: JAMboreeLite update failed with exit code !UPDATE_RC!.
    if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
    exit /b !UPDATE_RC!
)

echo.
echo Update completed from %REF% at !SOURCE_COMMIT!.
if /I not "!JAMBOREE_NO_PAUSE!"=="1" pause
exit /b 0
