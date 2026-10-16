@echo off
rem Installs (or updates) Utility Tracker for the current Windows user.
rem Program files go to %LOCALAPPDATA%\UtilityTracker; the data folder there is
rem never overwritten, so running this again updates the program and keeps the data.
setlocal
title Install Utility Tracker
set "SRC=%~dp0"
set "DEST=%LOCALAPPDATA%\UtilityTracker"

echo Installing Utility Tracker to %DEST% ...

rem Stop a running copy so its files can be replaced
if exist "%DEST%\python\python.exe" "%DEST%\python\python.exe" "%DEST%\app\serve.py" --stop >nul 2>&1

robocopy "%SRC%python" "%DEST%\python" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto failed
robocopy "%SRC%app" "%DEST%\app" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto failed
copy /y "%SRC%windows\Utility Tracker.bat" "%DEST%\" >nul
copy /y "%SRC%windows\Stop Utility Tracker.bat" "%DEST%\" >nul
copy /y "%SRC%windows\Uninstall Utility Tracker.bat" "%DEST%\" >nul

rem Data: only seeded on the first install, from data\utilities.db in this folder if present
if not exist "%DEST%\data" mkdir "%DEST%\data"
if exist "%SRC%data\utilities.db" if not exist "%DEST%\data\utilities.db" (
    copy "%SRC%data\utilities.db" "%DEST%\data\utilities.db" >nul
    echo Copied the database from this folder.
)

rem Shortcuts on the Desktop and in the Start menu
powershell -NoProfile -ExecutionPolicy Bypass -File "%SRC%windows\make-shortcuts.ps1" -Dest "%DEST%" >nul 2>&1
if errorlevel 1 (
    rem PowerShell not allowed here: put the launcher itself on the Desktop instead
    copy /y "%DEST%\Utility Tracker.bat" "%USERPROFILE%\Desktop\" >nul
)

echo.
echo Done. Utility Tracker is opening in your browser.
echo From now on, open it with the "Utility Tracker" shortcut on your Desktop or Start menu.
echo Your data is kept in %DEST%\data
start "" "%DEST%\python\pythonw.exe" "%DEST%\app\serve.py"
timeout /t 8 >nul
exit /b 0

:failed
echo.
echo Installation failed while copying files. Close Utility Tracker if it is open and try again.
pause
exit /b 1
