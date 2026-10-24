@echo off
cd /d "%~dp0.."
python tools\balance_editor.py --open
if errorlevel 1 pause
