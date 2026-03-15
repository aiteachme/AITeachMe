#!/usr/bin/env python3
"""
生成项目代码量变化趋势图表
基于 Git 历史记录统计代码行数，并生成可嵌入 README 的动态图表
支持增量更新，只分析新的提交
"""
import subprocess
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import re

# 脚本所在目录，用于定位 JSON 数据文件
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_JSON_PATH = str(SCRIPT_DIR / 'code_stats.json')


def run_git_command(cmd: List[str], ignore_errors: bool = False) -> str:
    """执行 Git 命令并返回输出
    
    Args:
        cmd: Git 命令列表
        ignore_errors: 是否忽略错误（用于读取可能不存在的文件）
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=not ignore_errors,
            encoding='utf-8',
            errors='replace',  # 遇到无法解码的字符时替换为 �
            timeout=30  # 30秒超时
        )
        return result.stdout.strip() if result.stdout else ""
    except subprocess.TimeoutExpired:
        if not ignore_errors:
            print(f"⚠️  命令超时: {' '.join(cmd[:3])}...")
        return ""
    except subprocess.CalledProcessError as e:
        if not ignore_errors:
            print(f"⚠️  命令失败: {' '.join(cmd[:3])}...")
        return ""
    except Exception as e:
        if not ignore_errors:
            print(f"⚠️  未知错误: {e}")
        return ""


def load_existing_stats(json_path: str = DEFAULT_JSON_PATH) -> Optional[Dict]:
    """加载已存在的统计数据"""
    json_file = Path(json_path)
    
    if not json_file.exists():
        return None
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️  无法读取现有统计数据: {e}")
        return None


def get_latest_commit_from_stats(existing_stats: Optional[Dict]) -> Optional[str]:
    """从现有统计数据中获取最新的提交哈希"""
    if not existing_stats or not existing_stats.get('stats'):
        return None
    
    return existing_stats['stats'][-1]['commit']


def get_commit_history(max_commits: int = 50, since_commit: Optional[str] = None, all_history: bool = False) -> List[Dict[str, str]]:
    """获取提交历史
    
    Args:
        max_commits: 最多获取的提交数
        since_commit: 从这个提交之后开始获取（不包含该提交）
        all_history: 是否获取所有历史提交
    """
    if all_history:
        print(f"📊 获取完整 Git 历史...")
        # 获取所有提交
        log_output = run_git_command([
            'git', 'log',
            '--all',
            '--pretty=format:%H|%ai|%s',
            '--reverse'
        ])
    elif since_commit:
        print(f"📊 获取自 {since_commit[:7]} 之后的新提交...")
        # 获取指定提交之后的所有提交
        log_output = run_git_command([
            'git', 'log',
            f'{since_commit}..HEAD',
            '--pretty=format:%H|%ai|%s',
            '--reverse'
        ])
    else:
        print(f"📊 获取最近 {max_commits} 次提交记录...")
        log_output = run_git_command([
            'git', 'log',
            f'-{max_commits}',
            '--pretty=format:%H|%ai|%s',
            '--reverse'
        ])
    
    if not log_output:
        return []
    
    commits = []
    for line in log_output.split('\n'):
        if not line:
            continue
        parts = line.split('|', 2)
        if len(parts) >= 2:
            commits.append({
                'hash': parts[0],
                'date': parts[1][:10],
                'message': parts[2] if len(parts) > 2 else ''
            })
    
    return commits


def count_lines_at_commit(commit_hash: str) -> Tuple[int, int, int]:
    """统计指定提交的代码行数
    
    返回: (总行数, 代码行数, 注释+空行数)
    """
    # 获取该提交时的所有文件
    files_output = run_git_command([
        'git', 'ls-tree', '-r', '--name-only', commit_hash
    ])
    
    if not files_output:
        return 0, 0, 0
    
    files = files_output.split('\n')
    
    # 过滤代码文件（排除二进制文件、依赖等）
    code_extensions = {
        '.py', '.js', '.ts', '.tsx', '.jsx', '.vue', '.go', '.rs',
        '.java', '.cpp', '.c', '.h', '.hpp', '.cs', '.rb', '.php',
        '.swift', '.kt', '.scala', '.sh', '.bash', '.sql', '.md'
    }
    
    exclude_patterns = [
        'node_modules/', '.venv/', 'venv/', '__pycache__/', '.git/',
        'dist/', 'build/', '.pytest_cache/', 'target/', '.egg-info/',
        'migrations/', 'alembic/versions/'
    ]
    
    total_lines = 0
    code_lines = 0
    
    for file_path in files:
        if not file_path:
            continue
            
        # 检查是否应该排除
        if any(pattern in file_path for pattern in exclude_patterns):
            continue
            
        # 检查文件扩展名
        ext = Path(file_path).suffix.lower()
        if ext not in code_extensions:
            continue
        
        try:
            # 获取文件内容（忽略错误，因为某些文件可能无法读取）
            content = run_git_command([
                'git', 'show', f'{commit_hash}:{file_path}'
            ], ignore_errors=True)
            
            if not content:
                continue
            
            lines = content.split('\n')
            total_lines += len(lines)
            
            # 简单统计：非空行且不是纯注释行
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith(('#', '//', '/*', '*', '*/')):
                    code_lines += 1
                    
        except Exception as e:
            # 文件可能是二进制或无法读取，跳过
            continue
    
    return total_lines, code_lines, total_lines - code_lines


def generate_stats_data(max_commits: int = 50, incremental: bool = True, all_history: bool = False) -> Dict:
    """生成统计数据
    
    Args:
        max_commits: 最多分析的提交数（仅在非增量模式下使用）
        incremental: 是否使用增量更新模式
        all_history: 是否分析完整 Git 历史
    """
    existing_stats = None
    since_commit = None
    
    # 如果是完整历史模式，忽略增量更新
    if all_history:
        incremental = False
        print("🔄 完整历史模式：将分析所有 Git 提交")
    
    # 尝试加载现有数据
    if incremental and not all_history:
        existing_stats = load_existing_stats()
        if existing_stats:
            since_commit = get_latest_commit_from_stats(existing_stats)
            if since_commit:
                print(f"✓ 找到现有统计数据，最新提交: {since_commit[:7]}")
    
    # 获取提交历史
    if all_history:
        commits = get_commit_history(all_history=True)
    elif since_commit:
        commits = get_commit_history(since_commit=since_commit)
    else:
        commits = get_commit_history(max_commits)
    
    if not commits:
        if existing_stats:
            print("ℹ️  没有新的提交，使用现有数据")
            return existing_stats
        else:
            print("❌ 没有找到提交记录")
            sys.exit(1)
    
    print(f"✓ 找到 {len(commits)} 次{'新' if since_commit else ''}提交")
    
    # 如果是增量更新，从现有数据开始
    if existing_stats and since_commit:
        stats = existing_stats['stats'].copy()
        print(f"📈 增量分析 {len(commits)} 个新提交...")
    else:
        stats = []
        # 不再采样，保存所有数据
        print(f"📈 分析 {len(commits)} 个提交...")
    
    # 分析提交
    failed_commits = 0
    for i, commit in enumerate(commits, 1):
        try:
            print(f"  [{i}/{len(commits)}] {commit['date']} {commit['hash'][:7]}", end='')
            
            total, code, other = count_lines_at_commit(commit['hash'])
            
            # 如果统计结果为0，可能是出错了，但继续处理
            if total == 0 and code == 0:
                print(" ⚠️  (无数据)")
                failed_commits += 1
            else:
                print(f" ✓ ({code:,} 行)")
            
            stats.append({
                'date': commit['date'],
                'commit': commit['hash'][:7],
                'total_lines': total,
                'code_lines': code,
                'other_lines': other,
                'message': commit['message'][:50]
            })
        except Exception as e:
            print(f" ❌ 错误: {e}")
            failed_commits += 1
            # 继续处理下一个提交
            continue
    
    if failed_commits > 0:
        print(f"\n⚠️  {failed_commits} 个提交处理失败或无数据")
    
    # 不再限制数据点数量，保存所有数据
    # 图表生成时会自动采样
    print(f"💾 保存 {len(stats)} 个数据点")
    
    return {
        'generated_at': datetime.now().isoformat(),
        'total_commits_analyzed': len(stats),
        'stats': stats
    }


def save_stats_json(data: Dict, output_path: str = DEFAULT_JSON_PATH):
    """保存统计数据为 JSON"""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ 统计数据已保存到: {output_file}")


def generate_shields_io_badge(data: Dict) -> str:
    """生成 Shields.io 徽章 URL"""
    if not data['stats']:
        return ""
    
    latest = data['stats'][-1]
    total_lines = latest['total_lines']
    
    # 格式化数字（添加千位分隔符）
    if total_lines >= 1000:
        formatted = f"{total_lines/1000:.1f}k"
    else:
        formatted = str(total_lines)
    
    # 使用 Shields.io 动态徽章
    badge_url = f"https://img.shields.io/badge/代码行数-{formatted}-blue"
    
    return badge_url


def generate_quickchart_url(data: Dict) -> str:
    """生成 QuickChart.io 图表 URL（自动采样以适应 URL 长度限制）"""
    if not data['stats']:
        return ""
    
    # 采样数据以适应图表显示和 URL 长度限制
    stats = data['stats']
    max_points = 100  # 图表最多显示 100 个点
    
    if len(stats) > max_points:
        # 采样：均匀选取数据点
        sample_interval = len(stats) / max_points
        sampled_stats = [stats[int(i * sample_interval)] for i in range(max_points)]
        print(f"📊 图表采样：{len(stats)} 个数据点 → {len(sampled_stats)} 个显示点")
    else:
        sampled_stats = stats
    
    # 准备数据
    dates = [stat['date'] for stat in sampled_stats]
    code_lines = [stat['code_lines'] for stat in sampled_stats]
    other_lines = [stat['other_lines'] for stat in sampled_stats]
    
    # 简化日期标签（只显示部分）
    label_interval = max(1, len(dates) // 8)
    labels = [dates[i] if i % label_interval == 0 else '' for i in range(len(dates))]
    
    # 构建 Chart.js 配置（堆叠面积图）
    chart_config = {
        'type': 'line',
        'data': {
            'labels': labels,
            'datasets': [{
                'label': '代码行数',
                'data': code_lines,
                'borderColor': 'rgb(75, 192, 192)',
                'backgroundColor': 'rgba(75, 192, 192, 0.5)',
                'fill': True,
                'tension': 0.4
            }, {
                'label': '注释/空行',
                'data': other_lines,
                'borderColor': 'rgb(255, 159, 64)',
                'backgroundColor': 'rgba(255, 159, 64, 0.5)',
                'fill': True,
                'tension': 0.4
            }]
        },
        'options': {
            'title': {
                'display': True,
                'text': 'FluxHive 代码量变化趋势',
                'fontSize': 16
            },
            'scales': {
                'yAxes': [{
                    'stacked': True,
                    'ticks': {
                        'beginAtZero': True
                    },
                    'scaleLabel': {
                        'display': True,
                        'labelString': '行数'
                    }
                }],
                'xAxes': [{
                    'stacked': True,
                    'scaleLabel': {
                        'display': True,
                        'labelString': '日期'
                    }
                }]
            },
            'legend': {
                'display': True
            }
        }
    }
    
    # 转换为 JSON 并编码
    import urllib.parse
    chart_json = json.dumps(chart_config, separators=(',', ':'))
    encoded = urllib.parse.quote(chart_json)
    
    # QuickChart.io URL
    chart_url = f"https://quickchart.io/chart?c={encoded}&width=800&height=400"
    
    return chart_url


def main():
    """主函数"""
    print("🚀 FluxHive 代码统计工具\n")
    
    # 检查是否在 Git 仓库中
    try:
        run_git_command(['git', 'rev-parse', '--git-dir'])
    except SystemExit:
        print("❌ 当前目录不是 Git 仓库")
        sys.exit(1)
    
    # 解析命令行参数
    max_commits = 50
    incremental = True
    all_history = False
    verbose = False
    
    for arg in sys.argv[1:]:
        if arg == '--full':
            incremental = False
            print("🔄 使用完全重建模式")
        elif arg == '--all':
            all_history = True
            incremental = False
            print("🔄 使用完整历史模式")
        elif arg == '--verbose' or arg == '-v':
            verbose = True
            print("🔍 详细模式已启用")
        elif arg == '--help' or arg == '-h':
            print("用法:")
            print("  python generate_code_stats.py [选项] [提交数]")
            print("\n选项:")
            print("  --full          完全重建统计数据（不使用增量更新）")
            print("  --all           分析完整 Git 历史（所有提交）")
            print("  --verbose, -v   显示详细调试信息")
            print("  --help, -h      显示帮助信息")
            print("\n示例:")
            print("  python generate_code_stats.py              # 增量更新（推荐）")
            print("  python generate_code_stats.py --full       # 完全重建，分析最近50次提交")
            print("  python generate_code_stats.py --full 100   # 完全重建，分析最近100次提交")
            print("  python generate_code_stats.py --all        # 分析完整 Git 历史")
            print("  python generate_code_stats.py --verbose    # 增量更新（显示详细信息）")
            print("\n说明:")
            print("  - 增量模式：只分析新提交，速度快（推荐日常使用）")
            print("  - 完全重建：重新分析指定数量的历史提交")
            print("  - 完整历史：分析所有提交，自动采样为100个数据点（首次运行推荐）")
            sys.exit(0)
        else:
            try:
                max_commits = int(arg)
            except ValueError:
                print(f"⚠️  无效的参数: {arg}，忽略")
    
    # 生成统计数据
    data = generate_stats_data(max_commits, incremental, all_history)
    
    # 保存 JSON
    save_stats_json(data)
    
    # 生成图表 URL
    chart_url = generate_quickchart_url(data)
    badge_url = generate_shields_io_badge(data)
    
    print(f"\n📊 统计摘要:")
    print(f"  - 分析提交数: {data['total_commits_analyzed']}")
    if data['stats']:
        latest = data['stats'][-1]
        first = data['stats'][0]
        print(f"  - 时间范围: {first['date']} 至 {latest['date']}")
        print(f"  - 当前代码行数: {latest['code_lines']:,}")
        print(f"  - 总行数: {latest['total_lines']:,}")
        
        if len(data['stats']) > 1:
            growth = latest['code_lines'] - first['code_lines']
            if first['code_lines'] > 0:
                growth_pct = growth / first['code_lines'] * 100
                print(f"  - 增长: {growth:+,} 行 ({growth_pct:+.1f}%)")
    
    print(f"\n🎨 可用的图表:")
    print(f"\n徽章 URL:")
    print(f"  {badge_url}")
    print(f"\n图表 URL:")
    print(f"  {chart_url}")
    
    print(f"\n📝 README 使用示例:")
    print(f"```markdown")
    print(f"![代码行数]({badge_url})")
    print(f"\n![代码量趋势]({chart_url})")
    print(f"```")
    
    print(f"\n✨ 完成！")
    if not all_history and incremental:
        print(f"💡 提示: 下次运行将自动增量更新，只分析新提交")
        print(f"   如需完全重建，使用: python {sys.argv[0]} --full")
        print(f"   如需分析完整历史，使用: python {sys.argv[0]} --all")


if __name__ == '__main__':
    main()
