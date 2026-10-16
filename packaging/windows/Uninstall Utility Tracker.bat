@echo off
rem Removes the program and its shortcuts. The data folder is kept unless you delete it yourself.
setlocal
title Uninstall Utility Tracker
set "DEST=%LOCALAPPDATA%\UtilityTracker"
choice /m "Remove Utility Tracker from this computer (your data folder is kept)"
if errorlevel 2 exit /b 0
"%DEST%\python\python.exe" "%DEST%\app\serve.py" --stop >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "foreach ($f in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { Remove-Item -LiteralPath (Join-Path $f 'Utility Tracker.lnk') -ErrorAction SilentlyContinue }" >nul 2>&1
del "%USERPROFILE%\Desktop\Utility Tracker.bat" >nul 2>&1
rmdir /s /q "%DEST%\python"
rmdir /s /q "%DEST%\app"
echo Removed. Your data is still in %DEST%\data
pause
del "%DEST%\Utility Tracker.bat" "%DEST%\Stop Utility Tracker.bat" >nul 2>&1
(goto) 2>nul & del "%~f0"
