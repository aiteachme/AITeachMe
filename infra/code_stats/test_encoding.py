#!/usr/bin/env python3
"""
测试 Git 命令的编码处理
"""
import subprocess

def test_git_encoding():
    """测试 Git 命令的编码处理"""
    print("测试 Git 编码处理...\n")
    
    # 测试 1: 获取最近的提交
    print("1. 测试获取提交历史...")
    try:
        result = subprocess.run(
            ['git', 'log', '-10', '--pretty=format:%H|%ai|%s'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=10
        )
        if result.returncode == 0:
            print(f"✓ 成功获取 {len(result.stdout.split(chr(10)))} 条提交记录")
        else:
            print(f"✗ 失败: {result.stderr}")
    except Exception as e:
        print(f"✗ 异常: {e}")
    
    # 测试 2: 获取最新提交的文件列表
    print("\n2. 测试获取文件列表...")
    try:
        result = subprocess.run(
            ['git', 'ls-tree', '-r', '--name-only', 'HEAD'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=10
        )
        if result.returncode == 0:
            files = [f for f in result.stdout.split('\n') if f]
            print(f"✓ 成功获取 {len(files)} 个文件")
            # 显示前5个文件
            for f in files[:5]:
                print(f"  - {f}")
        else:
            print(f"✗ 失败: {result.stderr}")
    except Exception as e:
        print(f"✗ 异常: {e}")
    
    # 测试 3: 读取一个文件内容
    print("\n3. 测试读取文件内容...")
    try:
        result = subprocess.run(
            ['git', 'show', 'HEAD:README.md'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=10
        )
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            print(f"✓ 成功读取文件，共 {len(lines)} 行")
            print(f"  前3行: {lines[:3]}")
        else:
            print(f"✗ 失败: {result.stderr}")
    except Exception as e:
        print(f"✗ 异常: {e}")
    
    print("\n✅ 编码测试完成")

if __name__ == '__main__':
    test_git_encoding()
