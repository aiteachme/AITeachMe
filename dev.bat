@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Ensure UTF-8 output when launched from PowerShell/cmd
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

title AITeachMe Dev

set "START_FLAGS="
set "START_ELECTRON=0"
set "SYNC_DEPS=1"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--headless" set "START_FLAGS=/B"
if /I "%~1"=="--electron" set "START_ELECTRON=1"
if /I "%~1"=="--no-electron" set "START_ELECTRON=0"
if /I "%~1"=="--no-sync" set "SYNC_DEPS=0"
shift
goto parse_args
:args_done

rem Always run from repo root (where this script lives)
pushd "%~dp0" >nul

rem Local dev ports: environment overrides .env, then defaults.
if exist ".env" (
	for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
		if /I "%%A"=="AITEACHME_BACKEND_PORT" if not defined AITEACHME_BACKEND_PORT set "AITEACHME_BACKEND_PORT=%%B"
		if /I "%%A"=="AITEACHME_FRONTEND_PORT" if not defined AITEACHME_FRONTEND_PORT set "AITEACHME_FRONTEND_PORT=%%B"
	)
)
if "%AITEACHME_BACKEND_PORT%"=="" set "AITEACHME_BACKEND_PORT=9020"
if "%AITEACHME_FRONTEND_PORT%"=="" set "AITEACHME_FRONTEND_PORT=5180"
set "BACKEND_HOST=127.0.0.1"
set "FRONTEND_HOST=127.0.0.1"

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
set "BACKEND_URL=http://%BACKEND_HOST%:%AITEACHME_BACKEND_PORT%"
set "FRONTEND_URL=http://%FRONTEND_HOST%:%AITEACHME_FRONTEND_PORT%"
set "PORT_SCAN_FILE=%TEMP%\aiteachme-dev-ports-%RANDOM%.txt"
netstat -ano -p tcp > "%PORT_SCAN_FILE%"
for /f "tokens=5" %%P in ('findstr /R /C:":%AITEACHME_BACKEND_PORT% .*LISTENING" "%PORT_SCAN_FILE%" 2^>nul') do if not defined BACKEND_PID set "BACKEND_PID=%%P"
for /f "tokens=5" %%P in ('findstr /R /C:":%AITEACHME_FRONTEND_PORT% .*LISTENING" "%PORT_SCAN_FILE%" 2^>nul') do if not defined FRONTEND_PID set "FRONTEND_PID=%%P"
del "%PORT_SCAN_FILE%" >nul 2>nul

if /I "%AITEACHME_SKIP_DEP_SYNC%"=="1" set "SYNC_DEPS=0"
if /I "%AITEACHME_SKIP_DEP_SYNC%"=="true" set "SYNC_DEPS=0"

if "%SYNC_DEPS%"=="1" (
	if not "%BACKEND_PID%"=="" (
		echo [Deps] Backend already running; skipping backend dependency sync.
	) else (
		echo [Deps] Syncing backend Python dependencies...
		if /I "%BACKEND_MODE%"=="venv" (
			"%BACKEND_PY%" -m pip install -e "%~dp0backend[dev]"
		) else (
			"%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output python -m pip install -e "%~dp0backend[dev]"
		)
		if errorlevel 1 (
			echo [Deps] Backend dependency sync failed.
			popd >nul
			exit /b 1
		)
	)

	if not "%FRONTEND_PID%"=="" (
		echo [Deps] Frontend already running; skipping frontend dependency sync.
	) else (
		echo [Deps] Syncing frontend npm dependencies...
		pushd "%~dp0frontend" >nul
		set "FRONTEND_NEEDS_SYNC=1"
		if exist "node_modules\.package-lock.json" (
			if /I not "%AITEACHME_FORCE_DEP_SYNC%"=="1" (
				if /I not "%AITEACHME_FORCE_DEP_SYNC%"=="true" (
					if /I "%FRONTEND_MODE%"=="system" (
						call npm ls --depth=0 --silent >nul 2>nul
					) else (
						"%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output npm ls --depth=0 --silent >nul 2>nul
					)
					if not errorlevel 1 set "FRONTEND_NEEDS_SYNC=0"
				)
			)
		)
		if "!FRONTEND_NEEDS_SYNC!"=="0" (
			echo [Deps] Frontend dependencies are already installed.
		) else (
			if /I "%FRONTEND_MODE%"=="system" (
				call npm ci
			) else (
				"%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output npm ci
			)
			if errorlevel 1 (
				echo [Deps] Frontend dependency sync failed.
				popd >nul
				popd >nul
				exit /b 1
			)
		)
		popd >nul
	)
) else (
	echo [Deps] Dependency sync skipped.
)

if "%START_FLAGS%"=="" if not "%FRONTEND_PID%"=="" (
	powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-CimInstance Win32_Process -Filter 'ProcessId=%FRONTEND_PID%' -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -like '*AiTeachMe*frontend*vite*') { exit 0 } exit 1" >nul 2>nul
	if not errorlevel 1 (
		echo [Frontend] Existing Vite process has no reusable console, restarting PID %FRONTEND_PID%...
		taskkill /PID %FRONTEND_PID% /T /F >nul 2>nul
		set "FRONTEND_PID="
	)
)

if not "%BACKEND_PID%"=="" (
	echo [Backend] FastAPI is already running on %BACKEND_URL%, PID %BACKEND_PID%. Reusing it.
) else (
	echo [Backend] Starting FastAPI on %BACKEND_URL%...
	if /I "%BACKEND_MODE%"=="venv" (
		start "Backend" %START_FLAGS% /D "%~dp0backend" "%BACKEND_PY%" -m uvicorn app.main:app --reload --host %BACKEND_HOST% --port %AITEACHME_BACKEND_PORT%
	) else (
		start "Backend" %START_FLAGS% /D "%~dp0backend" "%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output python -m uvicorn app.main:app --reload --host %BACKEND_HOST% --port %AITEACHME_BACKEND_PORT%
	)
)

if not "%FRONTEND_PID%"=="" (
	echo [Frontend] Vite is already running on %FRONTEND_URL%, PID %FRONTEND_PID%. Reusing it.
) else (
	echo [Frontend] Starting Vite on %FRONTEND_URL%...
	if /I "%FRONTEND_MODE%"=="system" (
		if "%START_FLAGS%"=="" (
			start "Frontend" /D "%~dp0frontend" cmd /k "npm run dev"
		) else (
			start "Frontend" %START_FLAGS% /D "%~dp0frontend" npm run dev
		)
	) else (
		if "%START_FLAGS%"=="" (
			start "Frontend" /D "%~dp0frontend" cmd /k ""%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output npm run dev"
		) else (
			start "Frontend" %START_FLAGS% /D "%~dp0frontend" "%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output npm run dev
		)
	)
)

if "%START_FLAGS%"=="" if not "%START_ELECTRON%"=="1" (
	echo [Frontend] Opening %FRONTEND_URL%...
	start "" "%FRONTEND_URL%"
)

if "%START_ELECTRON%"=="1" (
	echo [Desktop] Starting Electron window...
	set "AITEACHME_ELECTRON_APP_ID=com.aiteachme.desktop.dev"
	set "AITEACHME_ELECTRON_PRODUCT_NAME=AiTeachMe Dev"
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
