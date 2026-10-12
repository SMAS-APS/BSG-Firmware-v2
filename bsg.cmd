@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0bsg.ps1" %*
if errorlevel 1 pause
