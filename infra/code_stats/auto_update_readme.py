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


def load_stats_data(json_path: str = 'tools/code_stats/code_stats.json') -> dict:
    """加载统计数据"""
    json_file = Path(json_path)
    
    if not json_file.exists():
        print(f"❌ 统计数据文件不存在: {json_file}")
        print("💡 请先运行: python tools/code_stats/generate_code_stats.py")
        sys.exit(1)
    
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def update_readme(data: dict, readme_path: str = 'README.md'):
    """更新 README 中的图表 URL"""
    readme_file = Path(readme_path)
    
    if not readme_file.exists():
        print(f"❌ README 文件不存在: {readme_file}")
        sys.exit(1)
    
    # 读取 README
    with open(readme_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 生成新的 URL
    chart_url = generate_quickchart_url(data)
    badge_url = generate_shields_io_badge(data)
    
    # 更新徽章 URL（在 header 部分）
    badge_pattern = r'https://img\.shields\.io/badge/代码行数-[^"]+?-blue'
    if re.search(badge_pattern, content):
        content = re.sub(badge_pattern, badge_url, content)
        print("✓ 已更新代码行数徽章")
    else:
        print("⚠️  未找到代码行数徽章，跳过更新")
    
    # 更新图表 URL（在代码量变化趋势部分）
    chart_pattern = r'!\[代码量趋势\]\(https://quickchart\.io/chart\?c=[^\)]+\)'
    new_chart_markdown = f'![代码量趋势]({chart_url})'
    
    if re.search(chart_pattern, content):
        content = re.sub(chart_pattern, new_chart_markdown, content)
        print("✓ 已更新代码量趋势图表")
    else:
        print("⚠️  未找到代码量趋势图表，跳过更新")
    
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
