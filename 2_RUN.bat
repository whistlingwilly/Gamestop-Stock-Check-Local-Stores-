@echo off
title Pokemon GameStop Checker
py gamestop_checker_gui.py
if %errorlevel% neq 0 (
    echo.
    echo  Something went wrong. Have you run "1_SETUP" yet?
    echo  If not, double-click "1_SETUP (run this first).bat" first.
    echo.
    pause
)
