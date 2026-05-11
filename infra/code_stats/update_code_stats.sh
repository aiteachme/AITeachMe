#!/bin/bash
# 更新代码统计数据并更新 README
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

echo "正在增量更新代码统计数据..."
python3 infra/code_stats/generate_code_stats.py

if [ $? -eq 0 ]; then
    echo ""
    echo "正在更新 README..."
    python3 infra/code_stats/auto_update_readme.py
    
    if [ $? -eq 0 ]; then
        echo ""
        echo "✅ 统计数据和 README 已更新"
        echo "💡 请查看 infra/code_stats/code_stats.json 和 README.md"
        echo ""
        echo "💡 提示: 如需完全重建统计数据，使用:"
        echo "   python3 infra/code_stats/generate_code_stats.py --full"
    else
        echo ""
        echo "⚠️  README 更新失败，但统计数据已生成"
    fi
else
    echo ""
    echo "❌ 更新失败"
    exit 1
fi
