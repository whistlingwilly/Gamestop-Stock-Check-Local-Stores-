@echo off
title Pokemon GameStop Checker - Setup
color 0A
echo.
echo  ============================================
echo    Pokemon GameStop Checker - First Time Setup
echo  ============================================
echo.
echo  This will install everything you need.
echo  It only needs to run once!
echo.
pause

:: Check Python is installed
py --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  ERROR: Python is not installed!
    echo.
    echo  Please do the following:
    echo    1. Go to https://www.python.org/downloads/
    echo    2. Download and run the installer
    echo    3. IMPORTANT: Check the box that says
    echo       "Add Python to PATH"
    echo    4. Run this setup file again
    echo.
    pause
    exit
)

echo.
echo  Python found! Installing packages...
echo.
py -m pip install patchright Pillow --quiet --no-warn-script-location
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  ERROR installing packages.
    echo  Check your internet connection and try again.
    pause
    exit
)

echo.
echo  Installing Chrome for Patchright (better stealth than Chromium)...
echo.
py -m patchright install chrome
if %errorlevel% neq 0 (
    echo  Chrome not available - installing Chromium fallback...
    py -m patchright install chromium
)

color 0A
echo.
echo  ============================================
echo    Setup complete!
echo    Now double-click  2_RUN.bat  to start.
echo  ============================================
echo.
echo  NOTE: The app waits 2-8 minutes before its
echo  first check. This is intentional - it avoids
echo  looking like a bot right after starting up.
echo.
pause
