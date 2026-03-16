# 后端设计概览

## 目标

本轮设计重点是把外部 API、内部分层和数据模型一次性收口。

## 分层

- `api`
  - 只做参数接收、调用 service、包装 `ApiResponse`
- `services`
  - 负责编排流程
  - 调用 `repositories` 和 `agents`
- `repositories`
  - 只做数据库增删改查
- `agents`
  - 只做解析、提示词、向量化、出题、判分、报告建议等 AI 或纯算法逻辑

## 资源设计

### subjects

- `add`
- `list`
- `get`
- `edit`
- `delete`

### files

- `upload`
- `parse`
- `retry`
- `status`
- `list`
- `get`
- `delete`

### knowledge

- `build`
- `retry`
- `status`
- `list`
- `get`
- `tree`
- `delete`

### chat

- `send`
- `list`
- `clear`

### exam

- `make`
- `submit`
- `list`
- `delete`

### profile

- `list`
- `report`
- `mistakes`

## 数据模型

- `Subject`
- `RawFile`
- `DocSet`
- `DocBuildJob`
- `DocSetSourceFile`
- `Document`
- `DocumentChunk`
- `DocumentOutlineNode`
- `ChatMessage`
- `Exam`
- `Question`
- `ExamSubmission`
- `AnswerRecord`
- `Mistake`
- `UserProfile`

## 统一状态

### 任务状态

- `pending`
- `processing`
- `completed`
- `failed`

### 构建步骤

- `cleaned`
- `outlined`
- `stored`
- `chunked`
- `embedded`
