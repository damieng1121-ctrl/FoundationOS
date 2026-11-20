@echo off
rem Stoa Check: see if your apps, games and hardware work on Stoa. Nothing on this PC is changed.
title Stoa Check
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0StoaCheck.ps1"
if errorlevel 1 pause
