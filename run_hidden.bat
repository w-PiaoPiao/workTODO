@echo off
REM 切换到脚本所在目录（确保 main.py 路径正确）
cd /d "%~dp0"

REM Start without console window (production mode)
REM Uses pythonw.exe to avoid CMD window staying open.

start "" /B pythonw.exe main.py
exit 0
