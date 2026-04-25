@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-tauri-local.ps1" %*
exit /b %ERRORLEVEL%
