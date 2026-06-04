@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\scripts\build-all.ps1" %*
exit /b %ERRORLEVEL%
