@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Ensure UTF-8 output when launched from PowerShell/cmd
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

title AITeachMe Dev

set "START_FLAGS="
if /I "%~1"=="--headless" (
	set "START_FLAGS=/B"
)

rem Always run from repo root (where this script lives)
pushd "%~dp0" >nul

rem Prefer explicit env override, then default
set "CONDA_ENV_NAME=%AITEACHME_CONDA_ENV%"
if "%CONDA_ENV_NAME%"=="" set "CONDA_ENV_NAME=aiteachme"

set "CONDA_CMD="

rem 1) Explicit conda path override
if not "%AITEACHME_CONDA_EXE%"=="" if exist "%AITEACHME_CONDA_EXE%" (
	set "CONDA_CMD=%AITEACHME_CONDA_EXE%"
)

rem 2) PATH discovery
if "%CONDA_CMD%"=="" (
	for /f "delims=" %%I in ('where conda.exe 2^>nul') do (
		if not defined CONDA_CMD set "CONDA_CMD=%%I"
	)
)

rem 3) Common fallback locations
if "%CONDA_CMD%"=="" if exist "%USERPROFILE%\Anaconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\Anaconda3\Scripts\conda.exe"
if "%CONDA_CMD%"=="" if exist "%USERPROFILE%\Miniconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\Miniconda3\Scripts\conda.exe"
if "%CONDA_CMD%"=="" if exist "D:\Env\Anaconda3\Scripts\conda.exe" set "CONDA_CMD=D:\Env\Anaconda3\Scripts\conda.exe"
if "%CONDA_CMD%"=="" if exist "D:\Anaconda\Scripts\conda.exe" set "CONDA_CMD=D:\Anaconda\Scripts\conda.exe"
if "%CONDA_CMD%"=="" if exist "C:\Anaconda\Scripts\conda.exe" set "CONDA_CMD=C:\Anaconda\Scripts\conda.exe"
if "%CONDA_CMD%"=="" if exist "C:\ProgramData\Anaconda3\Scripts\conda.exe" set "CONDA_CMD=C:\ProgramData\Anaconda3\Scripts\conda.exe"
if "%CONDA_CMD%"=="" if exist "C:\ProgramData\Miniconda3\Scripts\conda.exe" set "CONDA_CMD=C:\ProgramData\Miniconda3\Scripts\conda.exe"

set "BACKEND_MODE="
set "BACKEND_PY="
if exist ".venv\Scripts\python.exe" (
	set "BACKEND_MODE=venv"
	set "BACKEND_PY=%~dp0.venv\Scripts\python.exe"
) else (
	if not "%CONDA_CMD%"=="" (
		set "BACKEND_MODE=conda"
	)
)

set "FRONTEND_MODE="
where npm >nul 2>nul
if not errorlevel 1 (
	set "FRONTEND_MODE=system"
) else (
	if not "%CONDA_CMD%"=="" (
		set "FRONTEND_MODE=conda"
	)
)

if "%BACKEND_MODE%"=="" (
	echo [Backend] Startup failed: no .venv python and no usable conda found.
	echo   - Option 1: create .venv in repo root
	echo   - Option 2: put conda.exe in PATH
	echo   - Option 3: set AITEACHME_CONDA_EXE to conda.exe full path
	popd >nul
	exit /b 1
)

if "%FRONTEND_MODE%"=="" (
	echo [Frontend] Startup failed: no npm and no usable conda found.
	echo   - Option 1: install Node.js and ensure npm is in PATH
	echo   - Option 2: put conda.exe in PATH
	echo   - Option 3: set AITEACHME_CONDA_EXE to conda.exe full path
	popd >nul
	exit /b 1
)

rem Preflight checks
if /I "%BACKEND_MODE%"=="conda" (
	"%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output python -V >nul 2>nul
	if errorlevel 1 (
		echo [Env] Conda is available, but python cannot run in env "%CONDA_ENV_NAME%".
		echo   - Check env name and set AITEACHME_CONDA_ENV if needed.
		popd >nul
		exit /b 1
	)
)

if /I "%FRONTEND_MODE%"=="conda" (
	"%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output npm -v >nul 2>nul
	if errorlevel 1 (
		echo [Env] Conda env "%CONDA_ENV_NAME%" has no npm.
		echo   - Try: conda install -n %CONDA_ENV_NAME% -c conda-forge nodejs=22
		popd >nul
		exit /b 1
	)
)

echo [Backend] Starting FastAPI (http://localhost:8000)...
if /I "%BACKEND_MODE%"=="venv" (
	start "Backend" %START_FLAGS% /D "%~dp0backend" "%BACKEND_PY%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
) else (
	start "Backend" %START_FLAGS% /D "%~dp0backend" "%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
)

echo [Frontend] Starting Vite (http://localhost:5173)...
if /I "%FRONTEND_MODE%"=="system" (
	start "Frontend" %START_FLAGS% /D "%~dp0frontend" npm run dev
) else (
	start "Frontend" %START_FLAGS% /D "%~dp0frontend" "%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output npm run dev
)

echo Services started. Close each window to stop that service.
echo If browser cannot open, check logs in Backend/Frontend windows.

popd >nul
endlocal
