@echo off
REM 更新代码统计数据并更新 README
echo 正在增量更新代码统计数据...
python tools/code_stats/generate_code_stats.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo 正在更新 README...
    python tools/code_stats/auto_update_readme.py
    
    if %ERRORLEVEL% EQU 0 (
        echo.
        echo ? 统计数据和 README 已更新
        echo ? 请查看 tools/code_stats/code_stats.json 和 README.md
        echo.
        echo ? 提示: 如需完全重建统计数据，使用:
        echo    python tools/code_stats/generate_code_stats.py --full
    ) else (
        echo.
        echo ??  README 更新失败，但统计数据已生成
    )
) else (
    echo.
    echo ? 更新失败
    exit /b 1
)
