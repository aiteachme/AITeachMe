@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-android.ps1" %*
exit /b %ERRORLEVEL%
