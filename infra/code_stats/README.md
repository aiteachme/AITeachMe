# 代码统计工具使用说明

## 功能介绍

`generate_code_stats.py` 是一个基于 Git 历史记录的代码量统计工具，可以：

- 📊 分析项目代码量变化趋势
- 📈 生成动态图表（使用 QuickChart.io）
- 🏷️ 生成代码行数徽章（使用 Shields.io）
- 💾 保存统计数据为 JSON 格式（**完整数据，不采样**）
- ⚡ **支持增量更新**：只分析新提交，速度快
- 🎨 **智能图表采样**：保存完整数据，图表显示时自动采样

## 快速开始

### 首次使用（推荐）

```bash
# 1. 分析完整 Git 历史（首次运行推荐）
python infra/code_stats/generate_code_stats.py --all

# 2. 更新 README 中的图表
python infra/code_stats/auto_update_readme.py
```

### 日常使用

```bash
# 使用批处理脚本（自动增量更新）
infra\code_stats\update_code_stats.bat  # Windows
./infra/code_stats/update_code_stats.sh  # Linux/Mac
```

## 快速使用

### 方式一：使用批处理脚本（推荐）

```bash
# Windows
infra\code_stats\update_code_stats.bat

# Linux/Mac
chmod +x infra/code_stats/update_code_stats.sh
./infra/code_stats/update_code_stats.sh
```

### 方式二：直接运行 Python 脚本

```bash
# 增量更新（默认，推荐）- 只分析新提交
python infra/code_stats/generate_code_stats.py

# 完全重建 - 重新分析最近 50 次提交
python infra/code_stats/generate_code_stats.py --full

# 完全重建 - 重新分析最近 100 次提交
python infra/code_stats/generate_code_stats.py --full 100

# 完整历史 - 分析所有 Git 提交（首次运行推荐）
python infra/code_stats/generate_code_stats.py --all

# 查看帮助
python infra/code_stats/generate_code_stats.py --help
```

**三种模式对比**：

| 模式 | 命令 | 适用场景 | 速度 |
|------|------|----------|------|
| 增量更新 | `python generate_code_stats.py` | 日常使用，只分析新提交 | ⚡ 很快（3-10秒） |
| 完全重建 | `python generate_code_stats.py --full [N]` | 重新分析最近 N 次提交 | 🐢 较慢（30-60秒） |
| 完整历史 | `python generate_code_stats.py --all` | 首次运行，分析所有历史 | 🐌 最慢（1-5分钟） |

**说明**：
- ⚡ **增量更新**：只分析自上次统计以来的新提交，速度快
- 🔄 **完全重建**：重新分析指定数量的历史提交
- 📊 **完整历史**：分析所有提交，自动采样为 100 个数据点
- 💾 所有模式都会自动保留历史数据（最多 100 个数据点）

## 输出说明

### 1. JSON 数据文件

统计数据保存在 `infra/code_stats/code_stats.json`，包含：

```json
{
  "generated_at": "2026-02-06T10:30:00",
  "total_commits_analyzed": 30,
  "stats": [
    {
      "date": "2026-01-29",
      "commit": "5d7af31",
      "total_lines": 152000,
      "code_lines": 114061,
      "other_lines": 37939,
      "message": "Initial commit"
    }
  ]
}
```

### 2. 动态图表 URL

工具会生成两种 URL：

#### 徽章 URL（Shields.io）
```
https://img.shields.io/badge/代码行数-171.5k-blue
```

显示效果：![代码行数](https://img.shields.io/badge/代码行数-171.5k-blue)

#### 折线图 URL（QuickChart.io）
```
https://quickchart.io/chart?c={...}
```

显示效果：完整的代码量变化趋势折线图

### 3. README 集成

工具运行后会输出可直接复制到 README 的 Markdown 代码：

```markdown
![代码行数](https://img.shields.io/badge/代码行数-171.5k-blue)

![代码量趋势](https://quickchart.io/chart?c=...)
```

## 统计规则

### 包含的文件类型

- Python: `.py`
- JavaScript/TypeScript: `.js`, `.ts`, `.tsx`, `.jsx`
- Web: `.vue`, `.html`, `.css`
- 其他语言: `.go`, `.rs`, `.java`, `.cpp`, `.c`, `.h`, `.cs`, `.rb`, `.php`, `.swift`, `.kt`, `.scala`
- 脚本和配置: `.sh`, `.bash`, `.sql`, `.md`

### 排除的目录

- 依赖目录: `node_modules/`, `.venv/`, `venv/`
- 构建产物: `dist/`, `build/`, `target/`
- 缓存: `__pycache__/`, `.pytest_cache/`, `.egg-info/`
- 数据库迁移: `migrations/`, `alembic/versions/`

### 代码行统计

- **总行数**: 包括所有行（代码、注释、空行）
- **代码行数**: 排除空行和纯注释行
- **其他行数**: 注释和空行

## 自动化更新

### 方式一：使用更新脚本（推荐）

```bash
# Windows
infra\code_stats\update_code_stats.bat

# Linux/Mac
chmod +x infra/code_stats/update_code_stats.sh
./infra/code_stats/update_code_stats.sh
```

这个脚本会：
1. 生成最新的统计数据（`code_stats.json`）
2. 自动更新 README 中的图表 URL
3. 显示更新摘要

### 方式二：GitHub Actions 自动化

项目已配置 GitHub Actions 工作流（`.github/workflows/update-code-stats.yml`），会：

- ⏰ 每周一自动运行
- 🔄 自动提交更新到仓库
- 🚀 支持手动触发

手动触发方式：
1. 进入 GitHub 仓库的 Actions 页面
2. 选择 "Update Code Statistics" 工作流
3. 点击 "Run workflow"

### 方式三：Git Hook（本地自动化）

在 `.git/hooks/post-commit` 中添加：

```bash
#!/bin/bash
# 增量更新，速度很快
python infra/code_stats/generate_code_stats.py
python infra/code_stats/auto_update_readme.py
```

每次提交后自动更新统计数据（增量模式，只需几秒钟）。

### 方式四：定期手动更新

```bash
# 日常使用：增量更新（快速）
python infra/code_stats/generate_code_stats.py
python infra/code_stats/auto_update_readme.py

# 重要里程碑：完全重建（分析更多历史）
python infra/code_stats/generate_code_stats.py --full 100
python infra/code_stats/auto_update_readme.py
```

## 技术实现

### 增量更新机制

工具支持三种运行模式，满足不同需求：

#### 1. 增量更新模式（默认）
- **触发**：直接运行 `python generate_code_stats.py`
- **行为**：
  - 读取 `code_stats.json` 中的最新提交哈希
  - 只分析该提交之后的新提交
  - 将新数据追加到现有数据中
  - **保存所有数据，不采样**
- **性能**：⚡ 很快（3-10 秒）
- **适用**：日常使用

#### 2. 完全重建模式
- **触发**：`python generate_code_stats.py --full [N]`
- **行为**：
  - 重新分析最近 N 次提交（默认 50）
  - **保存所有数据，不采样**
  - 覆盖现有数据
- **性能**：🐢 较慢（30-60 秒）
- **适用**：首次运行、数据损坏、需要调整历史范围

#### 3. 完整历史模式
- **触发**：`python generate_code_stats.py --all`
- **行为**：
  - 分析所有 Git 历史提交
  - **保存所有数据，不采样**
  - 覆盖现有数据
- **性能**：🐌 最慢（1-5 分钟，取决于仓库大小）
- **适用**：首次运行、需要完整历史视图

#### 数据管理策略

**保存策略**：
- ✅ JSON 文件保存**所有**分析的数据点
- ✅ 不限制数据点数量
- ✅ 完整保留项目历史

**图表显示策略**：
- 📊 图表生成时自动采样为 100 个数据点
- 📊 保证图表可读性
- 📊 避免 URL 过长

**优势**：
- 💾 完整的历史数据用于分析
- 🎨 清晰的图表用于展示
- 🔄 可以随时调整图表采样策略而无需重新分析

**性能对比**：
- 增量更新 1-5 次新提交：~3-10 秒
- 完全重建 50 次提交：~30-60 秒
- 完整历史 500+ 次提交：~1-5 分钟

### 使用的服务

1. **QuickChart.io**: 免费的图表生成服务
   - 基于 Chart.js
   - 支持动态 URL 参数
   - 无需 API Key

2. **Shields.io**: 免费的徽章生成服务
   - 支持自定义文本和颜色
   - 广泛用于 GitHub 项目

### 数据采样策略

- 当提交数量超过 30 个时，自动按间隔采样
- 保证图表可读性，避免数据点过密
- 采样间隔 = max(1, 总提交数 // 30)