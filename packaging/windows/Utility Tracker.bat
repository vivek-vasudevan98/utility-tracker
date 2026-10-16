@echo off
rem Opens Utility Tracker in the browser, starting it first if it isn't running.
start "" "%~dp0python\pythonw.exe" "%~dp0app\serve.py"
