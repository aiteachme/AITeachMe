# Standard-02 Git 分支管理规范

**项目名称：AITeachMe**
**文档编号：Standard-02**
**版本：v1.0**
**状态：Active**
**适用范围：AITeachMe 全仓库**
**最后更新：2026-03-11**

---

## 1. 目的

本文档规范 AITeachMe 项目的 Git 分支命名、分支策略、合并流程与版本管理,确保代码演进清晰可追溯、团队协作高效有序。

---

## 2. 分支模型

采用简化的 Git Flow 模型,适配 MVP 到正式版的演进需求。

### 2.1 主要分支

#### `main`
- 生产环境分支
- 始终保持可部署状态
- 受保护,禁止直接推送
- 仅通过 PR 合并
- 每次合并打 tag

#### `develop`
- 开发主分支
- 集成所有已完成功能
- 定期合并到 `main`
- 受保护,禁止直接推送

### 2.2 辅助分支

#### Feature 分支
- 用途: 新功能开发
- 命名: `feature/<功能描述>`
- 基于: `develop`
- 合并到: `develop`
- 生命周期: 功能完成后删除

#### Bugfix 分支
- 用途: 非紧急 bug 修复
- 命名: `bugfix/<问题描述>`
- 基于: `develop`
- 合并到: `develop`
- 生命周期: 修复完成后删除

#### Hotfix 分支
- 用途: 生产环境紧急修复
- 命名: `hotfix/<问题描述>`
- 基于: `main`
- 合并到: `main` 和 `develop`
- 生命周期: 修复完成后删除

#### Release 分支
- 用途: 版本发布准备
- 命名: `release/v<版本号>`
- 基于: `develop`
- 合并到: `main` 和 `develop`
- 生命周期: 发布完成后删除

---

## 3. 分支命名规范

### 3.1 命名格式

```text
<类型>/<简短描述>
```

### 3.2 类型定义

| 类型 | 说明 | 示例 |
|------|------|------|
| `feature` | 新功能 | `feature/knowledge-graph` |
| `bugfix` | Bug 修复 | `bugfix/login-validation` |
| `hotfix` | 紧急修复 | `hotfix/security-patch` |
| `release` | 版本发布 | `release/v1.0.0` |
| `refactor` | 重构 | `refactor/api-layer` |
| `docs` | 文档更新 | `docs/api-guide` |
| `test` | 测试相关 | `test/unit-coverage` |
| `chore` | 工程配置 | `chore/ci-setup` |

### 3.3 命名规则

- 使用小写字母
- 使用短横线 `-` 分隔单词
- 描述简洁明确,3-5 个单词
- 禁止使用中文
- 禁止使用特殊字符 (除 `/` 和 `-`)

### 3.4 命名示例

**正确示例:**
```text
feature/ai-diagnosis-engine
bugfix/user-session-timeout
hotfix/payment-gateway-error
release/v1.2.0
refactor/database-layer
docs/deployment-guide
```

**错误示例:**
```text
feature/新功能          # 禁止中文
my-branch              # 缺少类型前缀
feature/fix_bug        # 类型错误,应为 bugfix
feature/this-is-a-very-long-branch-name-that-describes-everything  # 过长
```

---

## 4. 分支工作流

### 4.1 Feature 开发流程

```bash
# 1. 从 develop 创建 feature 分支
git checkout develop
git pull origin develop
git checkout -b feature/knowledge-graph

# 2. 开发并提交
git add .
git commit -m "feat: 实现知识图谱基础结构"

# 3. 推送到远程
git push origin feature/knowledge-graph

# 4. 创建 PR 到 develop
# 通过 GitHub/GitLab 界面操作

# 5. Code Review 通过后合并
# 通过 PR 界面操作

# 6. 删除本地和远程分支
git checkout develop
git pull origin develop
git branch -d feature/knowledge-graph
git push origin --delete feature/knowledge-graph
```

### 4.2 Hotfix 修复流程

```bash
# 1. 从 main 创建 hotfix 分支
git checkout main
git pull origin main
git checkout -b hotfix/critical-security-fix

# 2. 修复并提交
git add .
git commit -m "fix: 修复 XSS 安全漏洞"

# 3. 推送到远程
git push origin hotfix/critical-security-fix

# 4. 创建 PR 到 main
# 通过界面操作

# 5. 合并到 main 并打 tag
# 合并后执行:
git checkout main
git pull origin main
git tag -a v1.0.1 -m "Hotfix: 安全漏洞修复"
git push origin v1.0.1

# 6. 同步到 develop
git checkout develop
git pull origin develop
git merge main
git push origin develop

# 7. 删除 hotfix 分支
git branch -d hotfix/critical-security-fix
git push origin --delete hotfix/critical-security-fix
```

### 4.3 Release 发布流程

```bash
# 1. 从 develop 创建 release 分支
git checkout develop
git pull origin develop
git checkout -b release/v1.0.0

# 2. 版本准备 (更新版本号、changelog 等)
# 修改 package.json、pyproject.toml 等
git add .
git commit -m "chore: 准备 v1.0.0 发布"

# 3. 推送到远程
git push origin release/v1.0.0

# 4. 测试验证通过后,创建 PR 到 main
# 通过界面操作

# 5. 合并到 main 并打 tag
git checkout main
git pull origin main
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0

# 6. 同步到 develop
git checkout develop
git pull origin develop
git merge main
git push origin develop

# 7. 删除 release 分支
git branch -d release/v1.0.0
git push origin --delete release/v1.0.0
```

---

## 5. 合并规范

### 5.1 合并策略

| 场景 | 策略 | 说明 |
|------|------|------|
| Feature → Develop | Squash Merge | 保持 develop 历史清晰 |
| Bugfix → Develop | Squash Merge | 保持 develop 历史清晰 |
| Release → Main | Merge Commit | 保留完整发布历史 |
| Hotfix → Main | Merge Commit | 保留紧急修复记录 |
| Main → Develop | Merge Commit | 保持分支同步 |

### 5.2 Squash Merge 规则

合并 feature/bugfix 到 develop 时:
- 将多个 commit 压缩为一个
- Commit message 遵循 Conventional Commits
- 保留关键信息,删除临时提交

### 5.3 Merge Commit 规则

合并 release/hotfix 到 main 时:
- 保留所有 commit 历史
- 创建明确的 merge commit
- Merge commit 格式: `Merge branch '<分支名>' into main`

### 5.4 冲突解决

- 优先在 feature 分支解决冲突
- 冲突解决后重新测试
- 禁止强制推送覆盖他人代码
- 复杂冲突需团队讨论

---

## 6. Pull Request 规范

### 6.1 PR 标题格式

```text
<类型>(<范围>): <简短描述>
```

示例:
```text
feat(ai): 添加知识图谱构建功能
fix(auth): 修复登录超时问题
docs(api): 更新 API 文档
```

### 6.2 PR 描述模板

```markdown
## 变更类型
- [ ] 新功能
- [ ] Bug 修复
- [ ] 重构
- [ ] 文档更新
- [ ] 其他

## 变更说明
简要描述本次变更的内容和原因

## 测试情况
- [ ] 单元测试通过
- [ ] 集成测试通过
- [ ] 手动测试通过

## 相关 Issue
关联的 Issue 编号 (如有)

## 截图/演示
(如适用)

## 检查清单
- [ ] 代码符合项目规范
- [ ] 已添加必要的测试
- [ ] 文档已更新
- [ ] 无安全隐患
```

### 6.3 PR 审查要求

- 至少 1 人 approve 才能合并
- CI 检查必须全部通过
- 代码覆盖率不得降低
- 必须解决所有 review 意见

---

## 7. Commit Message 规范

### 7.1 格式

```text
<类型>(<范围>): <主题>

<正文>

<页脚>
```

### 7.2 类型定义

| 类型 | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档更新 |
| `style` | 代码格式 (不影响功能) |
| `refactor` | 重构 |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `chore` | 构建/工具配置 |
| `revert` | 回滚 |

### 7.3 示例

```text
feat(ai): 实现知识点自动提取功能

- 添加 NLP 模型调用接口
- 实现知识点结构化存储
- 添加单元测试覆盖

Closes #123
```

---

## 8. 版本管理

### 8.1 版本号规则

采用语义化版本 (Semantic Versioning):

```text
v<主版本>.<次版本>.<修订版本>
```

- 主版本: 不兼容的 API 变更
- 次版本: 向下兼容的功能新增
- 修订版本: 向下兼容的问题修复

### 8.2 Tag 命名

```text
v1.0.0
v1.1.0
v1.1.1
```

### 8.3 Tag 创建

```bash
# 创建带注释的 tag
git tag -a v1.0.0 -m "Release v1.0.0: 初始版本发布"

# 推送 tag
git push origin v1.0.0

# 推送所有 tag
git push origin --tags
```

---

## 9. 分支保护规则

### 9.1 `main` 分支保护

- 禁止直接推送
- 必须通过 PR 合并
- 需要至少 1 人 approve
- CI 检查必须通过
- 禁止强制推送
- 禁止删除

### 9.2 `develop` 分支保护

- 禁止直接推送
- 必须通过 PR 合并
- CI 检查必须通过
- 禁止强制推送

---

## 10. 禁止事项

1. 禁止在 `main` 和 `develop` 分支直接提交
2. 禁止使用 `git push --force` 覆盖远程分支 (除非明确授权)
3. 禁止提交包含敏感信息的代码 (密钥、密码等)
4. 禁止提交大文件 (>10MB) 到仓库
5. 禁止在 PR 未 review 的情况下自行合并
6. 禁止删除他人的分支 (除非明确沟通)
7. 禁止修改已推送的 commit 历史 (rebase -i 公共分支)

---

## 11. 最佳实践

### 11.1 分支管理

- 及时删除已合并的分支
- 定期同步 develop 到 feature 分支
- 保持分支生命周期短 (< 2 周)
- 大功能拆分为多个小 feature

### 11.2 提交管理

- 提交粒度适中,一次提交完成一个逻辑单元
- Commit message 清晰描述变更内容
- 提交前运行测试和 lint 检查
- 避免提交调试代码和临时文件

### 11.3 协作管理

- PR 创建后及时通知 reviewer
- 积极响应 review 意见
- 冲突及时解决,避免长期积压
- 重要变更提前沟通

---

## 12. 执行要求

- 所有开发人员必须遵守本规范
- Code Review 必须检查分支命名和提交规范
- CI 流程应包含分支命名和 commit message 检查
- 违反规范的 PR 不予合并

---

## 13. 文档归档路径

本文档保存为:

```text
docs/standards/standard-02-git-branch-management.md
```
