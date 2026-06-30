@echo off
REM Start without console window (production mode)
REM Uses pythonw.exe to avoid CMD window staying open.

start "" /B pythonw.exe main.py
exit 0
