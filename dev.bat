@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Ensure UTF-8 output (fix garbled Chinese when running from PowerShell)
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

rem Startup strategy:
rem 1) If .venv exists: use it for backend, system npm for frontend
rem 2) Else: try conda run (default env name: aiteachme) for both backend & frontend

set "CONDA_ENV_NAME=%AITEACHME_CONDA_ENV%"
if "%CONDA_ENV_NAME%"=="" set "CONDA_ENV_NAME=aiteachme"

set "CONDA_CMD="

rem 1) Prefer explicit path override
if not "%AITEACHME_CONDA_EXE%"=="" if exist "%AITEACHME_CONDA_EXE%" (
	set "CONDA_CMD=%AITEACHME_CONDA_EXE%"
)

rem 2) Try PATH discovery (returns the full path)
if "%CONDA_CMD%"=="" (
	for /f "delims=" %%I in ('where conda.exe 2^>nul') do (
		if not defined CONDA_CMD set "CONDA_CMD=%%I"
	)
)

rem 3) Fallback to common install locations
if "%CONDA_CMD%"=="" if exist "%USERPROFILE%\Anaconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\Anaconda3\Scripts\conda.exe"
if "%CONDA_CMD%"=="" if exist "%USERPROFILE%\Miniconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\Miniconda3\Scripts\conda.exe"
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
if not "%CONDA_CMD%"=="" (
	set "FRONTEND_MODE=conda"
) else (
	where npm >nul 2>nul
	if %ERRORLEVEL%==0 (
		set "FRONTEND_MODE=system"
	)
)

if "%BACKEND_MODE%"=="" (
	echo [后端] 启动失败：未找到 .venv，且 conda 不可用。
	echo  - 方案1：在仓库根目录创建 .venv 后再运行本脚本
	echo  - 方案2：确保 conda 在 PATH 中，或设置 AITEACHME_CONDA_EXE=conda.exe 的完整路径
	echo  - 方案3：设置环境变量 AITEACHME_CONDA_ENV 指向你的 env（默认 aiteachme）
	popd >nul
	exit /b 1
)

if "%FRONTEND_MODE%"=="" (
	echo [前端] 启动失败：未找到 npm，且 conda 不可用。
	echo  - 方案1：安装 Node.js 并确保 npm 在 PATH
	echo  - 方案2：确保 conda 在 PATH 中，或设置 AITEACHME_CONDA_EXE=conda.exe 的完整路径
	echo  - 方案3：确保 conda env 中已安装 nodejs（例如 conda install -c conda-forge nodejs=22）
	popd >nul
	exit /b 1
)

rem Preflight checks (fail fast with clear error)
if not "%CONDA_CMD%"=="" (
	"%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output python -V >nul 2>nul
	if not %ERRORLEVEL%==0 (
		echo [环境] conda 可用，但无法运行 env "%CONDA_ENV_NAME%" 的 python。
		echo  - 请确认 env 名称是否正确（可设置 AITEACHME_CONDA_ENV）
		popd >nul
		exit /b 1
	)
	"%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output npm -v >nul 2>nul
	if not %ERRORLEVEL%==0 (
		echo [环境] conda env "%CONDA_ENV_NAME%" 中没有 npm。
		echo  - 建议执行：conda install -n %CONDA_ENV_NAME% -c conda-forge nodejs=22
		popd >nul
		exit /b 1
	)
)

echo [后端] 启动 FastAPI (http://localhost:8000)...
if /I "%BACKEND_MODE%"=="venv" (
	start "Backend" %START_FLAGS% /D "%~dp0backend" "%BACKEND_PY%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
) else (
	start "Backend" %START_FLAGS% /D "%~dp0backend" "%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
)

echo [前端] 启动 Vite (http://localhost:5173)...
if /I "%FRONTEND_MODE%"=="system" (
	start "Frontend" %START_FLAGS% /D "%~dp0frontend" npm run dev
) else (
	start "Frontend" %START_FLAGS% /D "%~dp0frontend" "%CONDA_CMD%" run -n %CONDA_ENV_NAME% --no-capture-output npm run dev
)

echo 服务已启动，关闭对应窗口即可停止服务
echo 如果浏览器打不开，请先检查新打开的 Backend/Frontend 窗口是否有报错。

:END
popd >nul
endlocal
