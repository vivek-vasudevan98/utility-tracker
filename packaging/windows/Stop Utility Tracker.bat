@echo off
rem Stops Utility Tracker. It starts again next time the shortcut is opened.
"%~dp0python\python.exe" "%~dp0app\serve.py" --stop
timeout /t 3 >nul
