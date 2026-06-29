@echo off
REM 无命令行窗口启动待办事项应用
REM 使用 pythonw.exe 避免 CMD 窗口常驻

start "" /B pythonw.exe main.py
exit 0
