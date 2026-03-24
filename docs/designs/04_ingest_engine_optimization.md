# Ingest 引擎优化记录

## 优化时间
2026-03-23

## 优化背景

在解析数学试卷类 PDF 时发现以下问题：
1. LLM Vision OCR 返回 `[unclear]` 或拒绝响应
2. PDF 分类不够精准，数学试卷被误判为 `complex_pdf`
3. 提取的 drawing 图片没有被充分利用
4. 占位符替换逻辑混乱，导致 markdown 结构不清晰

## 优化内容

### 1. PDF 分类器优化

**文件**: `backend/app/workflows/ingest/parsing/classifier.py`

**改进点**:
- 新增 `formula_heavy_pdf` 分类，专门识别数学试卷类文档
- 增加公式密集页检测：`drawing_count >= 3 && char_count < 500`
- 计算 `formula_ratio`（公式密集页占比）
- 优化分类规则：
  ```python
  if formula_ratio > 0.5 and avg_density < 300:
      file_category = "formula_heavy_pdf"
      recommended_parser = "pymupdf_native"
  ```

**效果**:
- 数学试卷类文档能被正确识别
- 优先使用 `pymupdf_native` 提取 drawing
- 日志中会显示 `formula_ratio` 指标

### 2. LLM Vision OCR 改进

**文件**:
- `backend/app/workflows/ingest/prompts/prompts.py`
- `backend/app/workflows/ingest/parsing/image.py`

**改进点**:

#### Prompt 优化
- 中文 prompt 更详细、更专业
- 明确要求：
  - 行内公式用 `$...$`
  - 独立公式用 `$$...$$`
  - 使用标准 LaTeX 语法
  - 描述图表类型和核心信息
  - 禁止臆造内容

#### 错误处理增强
- 检测图片太小（< 100 bytes）
- 检测拒绝响应模式：
  - "请提供需要处理的图片"
  - "please provide"
  - "i cannot see"
  - "no image"
  - "unable to process"
- 所有失败情况统一返回 `[unclear]`
- 详细的错误日志

#### OCR 模型配置
- 支持单独配置 `OCR_MODEL`、`OCR_API_KEY`、`OCR_BASE_URL`
- 未配置时自动回退到 LLM 配置
- 直接使用 `litellm.acompletion` 调用

**效果**:
- OCR 识别率提升
- 数学公式能正确识别为 LaTeX
- 错误情况有明确日志

### 3. PDF 解析策略优化

**文件**: `backend/app/workflows/ingest/parsing/strategy.py`

**改进点**:

针对 `formula_heavy_pdf` 的专门策略：
```python
options.asset_image_limit = 32          # 大幅提升图片提取上限
options.asset_vision_ocr_limit = 24     # 强化 OCR 预算
options.skip_image_supplement = False   # 不跳过图片补充
options.enable_page_vision_ocr = False  # 不做整页 OCR
options.timeout_s = 150                 # 延长超时时间
```

**效果**:
- 数学试卷能提取更多公式图片
- OCR 预算充足
- 避免不必要的整页 OCR

### 4. PyMuPDF Native 解析器优化

**文件**: `backend/app/workflows/ingest/parsing/pdf.py`

**改进点**:
- 按页提取并立即插入图片
- 图片紧跟在对应页的文字后面
- 统计 embedded images 和 drawings 数量
- 日志更详细

**效果**:
- Markdown 结构更清晰
- 图片位置更准确
- 便于调试和追踪

### 5. 占位符替换逻辑优化

**文件**: `backend/app/workflows/ingest/parsing/asset_ocr.py`

**改进点**:
- OCR 结果用 markdown 代码块包裹
- 只显示有效的 OCR 结果（非空且不是 `[unclear]`）
- 确保返回的 markdown 格式正确

**效果**:
- OCR 内容更清晰
- 避免显示无效的 `[unclear]` 标记

### 6. 配置系统增强

**文件**:
- `backend/app/core/config.py`
- `backend/.env.example`

**改进点**:
- 新增配置项：
  - `ocr_model: str | None`
  - `ocr_api_key: str | None`
  - `ocr_base_url: str | None`
- 新增方法 `get_ocr_config()` 自动回退
- 优化 `.env.example` 文档结构

**效果**:
- 支持为 OCR 任务单独配置模型
- 配置文件更清晰易懂

## 测试建议

### 1. 配置 OCR 模型

在 `.env` 中添加（可选）：
```bash
# 使用专门的视觉模型
OCR_MODEL=qwen-vl-max
OCR_API_KEY=sk-your-api-key

# 或者使用支持 vision 的通用模型
LLM_MODEL=qwen-plus-latest
```

### 2. 重新解析测试文件

```bash
# 删除旧的解析结果
rm -rf backend/data/subj_*/raw_markdown/*.md
rm -rf backend/data/subj_*/assets/*

# 重新上传文件触发解析
```

### 3. 检查解析结果

查看日志中的关键指标：
- `category`: 应该是 `formula_heavy_pdf`
- `formula_ratio`: 公式密集页占比
- `total_images`: 提取的图片总数
- `embedded_images`: 嵌入图片数量
- `drawings`: drawing 数量

查看 markdown 文件：
- 图片是否按页组织
- OCR 结果是否有效
- 公式是否识别为 LaTeX

## 性能影响

### 成本
- Vision OCR 会调用多模态模型，成本较高
- 建议根据预算调整 `asset_vision_ocr_limit`

### 时间
- `formula_heavy_pdf` 的 timeout 为 150s
- 实际解析时间取决于：
  - 文件大小
  - 图片数量
  - OCR 并发度

### 优化建议
1. 如果预算有限，降低 `asset_vision_ocr_limit`
2. 如果文件很大，增加 `timeout_s`
3. 如果 OCR 效果不好，尝试更强的视觉模型

## 后续优化方向

1. **智能 OCR 预算分配**
   - 根据图片复杂度动态调整 OCR 优先级
   - 优先 OCR 包含公式的图片

2. **缓存机制**
   - 对相同图片的 OCR 结果做缓存
   - 避免重复调用

3. **批量 OCR**
   - 支持批量发送图片到 OCR API
   - 提升并发效率

4. **OCR 质量评估**
   - 自动评估 OCR 结果质量
   - 对低质量结果重试或标记

5. **多模型融合**
   - 对关键图片使用多个模型 OCR
   - 融合结果提升准确率
