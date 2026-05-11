#!/usr/bin/env python3
"""
自动更新 README 中的代码统计图表
读取 code_stats.json 并更新 README.md 中的图表 URL
"""
import json
import re
import sys
from pathlib import Path
from generate_code_stats import generate_quickchart_url, generate_shields_io_badge

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_JSON_PATH = str(SCRIPT_DIR / 'code_stats.json')
DEFAULT_README_PATH = str(REPO_ROOT / 'README.md')
CODE_STATS_START = '<!-- CODE_STATS_START -->'
CODE_STATS_END = '<!-- CODE_STATS_END -->'


def load_stats_data(json_path: str = DEFAULT_JSON_PATH) -> dict:
    """加载统计数据"""
    json_file = Path(json_path)
    
    if not json_file.exists():
        print(f"❌ 统计数据文件不存在: {json_file}")
        print("💡 请先运行: python infra/code_stats/generate_code_stats.py")
        sys.exit(1)
    
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_code_stats_block(data: dict) -> str:
    """生成根 README 中展示用的代码统计区块。"""
    chart_url = generate_quickchart_url(data)
    badge_url = generate_shields_io_badge(data)

    return (
        f"{CODE_STATS_START}\n"
        "## 代码量概览\n\n"
        f"![代码行数]({badge_url})\n\n"
        f"![代码量趋势]({chart_url})\n"
        f"{CODE_STATS_END}"
    )


def update_readme(data: dict, readme_path: str = DEFAULT_README_PATH):
    """更新 README 中的图表 URL"""
    readme_file = Path(readme_path)
    
    if not readme_file.exists():
        print(f"❌ README 文件不存在: {readme_file}")
        sys.exit(1)
    
    # 读取 README
    with open(readme_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_block = build_code_stats_block(data)
    block_pattern = re.compile(
        rf'{re.escape(CODE_STATS_START)}.*?{re.escape(CODE_STATS_END)}',
        re.DOTALL,
    )

    if block_pattern.search(content):
        content = block_pattern.sub(new_block, content)
        print("✓ 已更新代码量统计区块")
    else:
        anchor = "\n## 核心闭环\n"
        if anchor in content:
            content = content.replace(anchor, f"\n{new_block}\n{anchor}", 1)
            print("✓ 已插入代码量统计区块")
        else:
            content = content.rstrip() + f"\n\n{new_block}\n"
            print("✓ 已在 README 末尾追加代码量统计区块")
    
    # 写回 README
    with open(readme_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ README 已更新: {readme_file}")


def main():
    """主函数"""
    print("🔄 自动更新 README 中的代码统计图表\n")
    
    # 加载统计数据
    data = load_stats_data()
    
    print(f"📊 统计数据:")
    if data['stats']:
        latest = data['stats'][-1]
        print(f"  - 最新日期: {latest['date']}")
        print(f"  - 代码行数: {latest['code_lines']:,}")
        print(f"  - 总行数: {latest['total_lines']:,}")
    
    print()
    
    # 更新 README
    update_readme(data)
    
    print("\n✨ 完成！")


if __name__ == '__main__':
    main()
