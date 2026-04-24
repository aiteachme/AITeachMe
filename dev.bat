@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Ensure UTF-8 output when launched from PowerShell/cmd
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

title AITeachMe Dev

set "START_FLAGS="
set "START_ELECTRON=0"
if /I "%~1"=="--headless" (
	set "START_FLAGS=/B"
)
if /I "%~2"=="--headless" (
	set "START_FLAGS=/B"
)
if /I "%~1"=="--electron" (
	set "START_ELECTRON=1"
)
if /I "%~2"=="--electron" (
	set "START_ELECTRON=1"
)
if /I "%~1"=="--no-electron" (
	set "START_ELECTRON=0"
)
if /I "%~2"=="--no-electron" (
	set "START_ELECTRON=0"
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

set "BACKEND_PID="
set "FRONTEND_PID="
set "PORT_SCAN_FILE=%TEMP%\aiteachme-dev-ports-%RANDOM%.txt"
netstat -ano -p tcp > "%PORT_SCAN_FILE%"
for /f "tokens=5" %%P in ('findstr /R /C:":8010 .*LISTENING" "%PORT_SCAN_FILE%" 2^>nul') do if not defined BACKEND_PID set "BACKEND_PID=%%P"
for /f "tokens=5" %%P in ('findstr /R /C:":5180 .*LISTENING" "%PORT_SCAN_FILE%" 2^>nul') do if not defined FRONTEND_PID set "FRONTEND_PID=%%P"
del "%PORT_SCAN_FILE%" >nul 2>nul

if not "%BACKEND_PID%"=="" (
	echo [Backend] FastAPI is already running on http://localhost:8010, PID %BACKEND_PID%. Reusing it.
) else (
	echo [Backend] Starting FastAPI on http://localhost:8010...
	if /I "%BACKEND_MODE%"=="venv" (
		start "Backend" %START_FLAGS% /D "%~dp0backend" "%BACKEND_PY%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
	) else (
		start "Backend" %START_FLAGS% /D "%~dp0backend" "%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
	)
)

if not "%FRONTEND_PID%"=="" (
	echo [Frontend] Vite is already running on http://localhost:5180, PID %FRONTEND_PID%. Reusing it.
) else (
	echo [Frontend] Starting Vite on http://localhost:5180...
	if /I "%FRONTEND_MODE%"=="system" (
		start "Frontend" %START_FLAGS% /D "%~dp0frontend" npm run dev
	) else (
		start "Frontend" %START_FLAGS% /D "%~dp0frontend" "%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output npm run dev
	)
)

if "%START_ELECTRON%"=="1" (
	echo [Desktop] Starting Electron window...
	if /I "%FRONTEND_MODE%"=="system" (
		start "Desktop" %START_FLAGS% /D "%~dp0frontend" npm run electron:window
	) else (
		start "Desktop" %START_FLAGS% /D "%~dp0frontend" "%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output npm run electron:window
	)
)

echo Services are ready. Close each service window to stop it.
echo If browser cannot open, check logs in Backend/Frontend windows.

popd >nul
endlocal
