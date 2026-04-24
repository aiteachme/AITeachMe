@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-electron-remote.ps1" %*
exit /b %ERRORLEVEL%
