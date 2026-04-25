@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-electron-local.ps1" %*
exit /b %ERRORLEVEL%
