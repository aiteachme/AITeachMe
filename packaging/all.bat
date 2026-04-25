@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-all.ps1" %*
exit /b %ERRORLEVEL%
