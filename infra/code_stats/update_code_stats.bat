@echo off
chcp 65001 >nul
REM 更新代码统计数据并更新 README
pushd "%~dp0..\.." >nul
echo 正在增量更新代码统计数据...
python infra/code_stats/generate_code_stats.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo 正在更新 README...
    python infra/code_stats/auto_update_readme.py

    if %ERRORLEVEL% EQU 0 (
        echo.
        echo [OK] 统计数据和 README 已更新
        echo [INFO] 请查看 infra/code_stats/code_stats.json 和 README.md
        echo.
        echo [TIP] 提示: 如需完全重建统计数据，使用:
        echo    python infra/code_stats/generate_code_stats.py --full
        popd >nul
    ) else (
        echo.
        echo [WARN] README 更新失败，但统计数据已生成
        popd >nul
        exit /b 1
    )
) else (
    echo.
    echo [ERROR] 更新失败
    popd >nul
    exit /b 1
)
