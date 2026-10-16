UTILITY TRACKER - WINDOWS PACKAGE
=================================

Nothing needs to be installed first: this folder contains its own Python.

INSTALL ON A COMPUTER
1. Copy this whole folder from the shared drive to the computer
   (or run it straight from the shared drive).
2. Double-click "Install Utility Tracker.bat".
   It copies the program to your user profile, adds a "Utility Tracker"
   shortcut to the Desktop and Start menu, and opens the app in your browser.

USE
Double-click the "Utility Tracker" shortcut. The app runs quietly in the
background and opens in your web browser at http://127.0.0.1:8765/
It is only reachable from this computer. Weather is downloaded from
Open-Meteo when needed, so the computer needs internet access.

BRINGING EXISTING DATA
Put an existing utilities.db file in the "data" folder here BEFORE installing,
and it is copied in on the first install. Or copy it later to:
    %LOCALAPPDATA%\UtilityTracker\data\utilities.db
(stop the app first with "Stop Utility Tracker" in that folder).

UPDATE
Run "Install Utility Tracker.bat" from a newer package. The program is replaced;
your data is kept.

WHERE THINGS ARE
Program:  %LOCALAPPDATA%\UtilityTracker\python and \app
Data:     %LOCALAPPDATA%\UtilityTracker\data   (database, settings, server.log)
Back up the data folder to keep your records safe.

STOP / UNINSTALL
"Stop Utility Tracker.bat" and "Uninstall Utility Tracker.bat" are in
%LOCALAPPDATA%\UtilityTracker. Uninstalling keeps the data folder.

IF IT DOESN'T OPEN
Look at %LOCALAPPDATA%\UtilityTracker\data\server.log
