@echo off
REM Launch the tray app silently (no console window). Put a shortcut to this in
REM shell:startup to have it run on login.
cd /d "%~dp0"
start "" pythonw -m pii_blur.tray
