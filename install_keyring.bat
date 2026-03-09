@echo off
REM JAMboreeLite Keyring Installation Script
REM Installs the keyring module for secure credential storage

echo ============================================================
echo JAMboreeLite - Installing Keyring Module
echo ============================================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    echo Please install Python 3.11+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Python found:
python --version
echo.

REM Check if we are in a virtual environment
python -c "import sys; exit(0 if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix) else 1)" >nul 2>&1
if errorlevel 1 (
    echo WARNING: Not in a virtual environment
    echo It is recommended to activate your venv first
    echo.
    echo To activate venv:
    echo   .venv\Scripts\activate
    echo   OR
    echo   venv\Scripts\activate
    echo.
    set /p CONTINUE="Continue anyway? (y/n): "
    if /i not "!CONTINUE!"=="y" (
        echo Installation cancelled
        pause
        exit /b 1
    )
)

echo Installing keyring module...
echo.
python -m pip install keyring==24.2.0

if errorlevel 1 (
    echo.
    echo ERROR: Failed to install keyring
    echo Try manually: pip install keyring==24.2.0
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Keyring Installation Complete!
echo ============================================================
echo.
echo The keyring module is now installed and ready to use.
echo.
echo Next steps:
echo   1. Run migration script: python migrate_credentials.py --verify
echo   2. Migrate credentials: python migrate_credentials.py
echo.
pause
