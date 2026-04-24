@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-tauri-remote.ps1" %*
exit /b %ERRORLEVEL%
