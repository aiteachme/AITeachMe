# 手动联调

这轮以后端架构重构后的接口为准，重点验证统一响应、分页、重试和删除能力。

## 1. 启动服务

```bash
uvicorn app.main:app --reload --port 8000
```

## 2. 基础检查

### 健康检查

```bash
curl http://localhost:8000/api/health
```

### 系统初始化

```bash
curl -X POST http://localhost:8000/api/v1/system/init ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

## 3. 学科

### 创建学科

```bash
curl -X POST http://localhost:8000/api/v1/subjects/add ^
  -H "Content-Type: application/json" ^
  -d "{\"subject\":\"math\",\"name\":\"高等数学\",\"description\":\"手动联调用\"}"
```

### 学科列表

```bash
curl -X POST http://localhost:8000/api/v1/subjects/list ^
  -H "Content-Type: application/json" ^
  -d "{\"page\":1,\"size\":20}"
```

## 4. 文件阶段

### 上传多个文件

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/upload" ^
  -F "files=@C:\path\to\lesson1.pdf" ^
  -F "files=@C:\path\to\lesson2.pdf"
```

### 查看文件列表

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/list" ^
  -H "Content-Type: application/json" ^
  -d "{\"page\":1,\"size\":20}"
```

### 触发解析

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/parse" ^
  -H "Content-Type: application/json" ^
  -d "{\"file_ids\":[1,2]}"
```

### 查询单文件状态

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/status" ^
  -H "Content-Type: application/json" ^
  -d "{\"file_id\":1}"
```

### 查看解析结果

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/get" ^
  -H "Content-Type: application/json" ^
  -d "{\"file_id\":1}"
```

### 重试失败文件

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/retry" ^
  -H "Content-Type: application/json" ^
  -d "{\"file_id\":1}"
```

### 删除文件

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/files/delete" ^
  -H "Content-Type: application/json" ^
  -d "{\"file_ids\":[2]}"
```

验收点：

1. `files/status` 只返回状态与错误信息，不返回全文。
2. `files/get` 能单独查看 Markdown。
3. `failed` 状态可以重试。
4. 已被知识集合引用的文件删除会被拒绝。

## 5. 知识集合阶段

### 构建知识集合

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/build" ^
  -H "Content-Type: application/json" ^
  -d "{\"file_ids\":[1,2],\"title\":\"概率论复习\",\"desc\":\"第一章到第三章\"}"
```

### 查询构建状态

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/status" ^
  -H "Content-Type: application/json" ^
  -d "{\"docset_id\":1}"
```

### 知识集合列表

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/list" ^
  -H "Content-Type: application/json" ^
  -d "{\"page\":1,\"size\":20}"
```

### 知识集合详情

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/get" ^
  -H "Content-Type: application/json" ^
  -d "{\"docset_id\":1}"
```

### 知识树

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/tree" ^
  -H "Content-Type: application/json" ^
  -d "{\"docset_id\":1}"
```

### 重试知识构建

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/retry" ^
  -H "Content-Type: application/json" ^
  -d "{\"docset_id\":1}"
```

### 删除知识集合

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/knowledge/delete" ^
  -H "Content-Type: application/json" ^
  -d "{\"docset_id\":1}"
```

验收点：

1. 一次 build 能消费多个文件。
2. 构建失败会进入 `failed`，并带 `error_message`。
3. 只有失败任务允许重试。
4. 删除知识集合后，关联的文档、切块和大纲会一起清理。

## 6. 下游能力

### 聊天

```bash
curl -N -X POST "http://localhost:8000/api/v1/subjects/math/chat/send" ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"解释一下条件概率\"}"
```

### 聊天列表

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/chat/list" ^
  -H "Content-Type: application/json" ^
  -d "{\"page\":1,\"size\":20}"
```

### 清空聊天

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/chat/clear" ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

### 生成试卷

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/exam/make" ^
  -H "Content-Type: application/json" ^
  -d "{\"num\":5}"
```

### 删除试卷

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/exam/delete" ^
  -H "Content-Type: application/json" ^
  -d "{\"exam_id\":1}"
```

### 学习报告

```bash
curl -X POST "http://localhost:8000/api/v1/subjects/math/profile/report" ^
  -H "Content-Type: application/json" ^
  -d "{}"
```
