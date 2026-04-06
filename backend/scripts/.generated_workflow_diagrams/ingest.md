# 📥 Ingest Engine · 摄入引擎

> 文件上传 → 快速传统解析 → 后台深度 OCR 增强，为下游 Digest 提供高质量文本素材。

**本模块包含以下子工作流：**

1. [Ingest Deep Enhance Workflow](#ingest-deep-enhance)
2. [Ingest File Parse Workflow](#ingest-parse)

---

## Ingest Deep Enhance Workflow

> Background deep OCR and enhancement workflow.

📊 **4** 个处理节点 · **8** 条边

```mermaid
flowchart TD
    __start__(["▶ START"])
    load_enhance_context["❶ Load Enhance Context"]
    deep_enhance_file["❷ Deep Enhance File"]
    finalize_deep_enhance(["❸ Finalize Deep Enhance"])
    __end__(["⏹ END"])

    subgraph error_zone ["⚠ 错误处理"]
    direction TB
        finalize_enhance_failure["⚠ Finalize Enhance Failure"]
    end

    __start__ --> load_enhance_context
    deep_enhance_file -->|"✓"| finalize_deep_enhance
    deep_enhance_file -. "✗ fail" .-> finalize_enhance_failure
    finalize_deep_enhance -->|"✓"| __end__
    finalize_deep_enhance -. "✗ fail" .-> finalize_enhance_failure
    load_enhance_context -->|"✓"| deep_enhance_file
    load_enhance_context -. "✗ fail" .-> finalize_enhance_failure
    finalize_enhance_failure --> __end__

    %% ── Styling ──
    classDef startCls fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#a7f3d0
    classDef endCls fill:#7f1d1d,stroke:#ef4444,stroke-width:2px,color:#fecaca
    classDef failCls fill:#4c0519,stroke:#f43f5e,stroke-width:2px,color:#fecdd3
    classDef termCls fill:#1e3a5f,stroke:#3b82f6,stroke-width:2px,color:#93c5fd
    classDef default fill:#1e293b,stroke:#475569,stroke-width:1px,color:#e2e8f0
    style error_zone fill:#1a0a0e,stroke:#f43f5e,stroke-width:1px,color:#fecdd3,stroke-dasharray:5
    class __start__ startCls
    class finalize_deep_enhance termCls
    class finalize_enhance_failure failCls
    class __end__ endCls
    linkStyle 2,4,6 stroke:#f43f5e,stroke-dasharray:5
```

**节点参考：**

| 节点 | 角色 | 路由 |
|------|------|------|
| Load Enhance Context | 🔀 条件路由 | `continue` → `fail` |
| Deep Enhance File | 🔀 条件路由 | `continue` → `fail` |
| Finalize Deep Enhance | 🔀 条件路由 | `continue` → `fail` |
| Finalize Enhance Failure | ❌ 错误处理 | → END |

## Ingest File Parse Workflow

> Single-file ingest parsing workflow.

📊 **7** 个处理节点 · **14** 条边

```mermaid
flowchart TD
    __start__(["▶ START"])
    load_raw_file["❶ Load Raw File"]
    compute_fingerprint["❷ Compute Fingerprint"]
    classify_file["❸ Classify File"]
    plan_parse["❹ Plan Parse"]
    parse_file["❺ Parse File"]
    finalize_success(["❻ Finalize Success"])
    __end__(["⏹ END"])

    subgraph error_zone ["⚠ 错误处理"]
    direction TB
        finalize_failure["⚠ Finalize Failure"]
    end

    __start__ --> load_raw_file
    classify_file -. "✗ fail" .-> finalize_failure
    classify_file -->|"✓"| plan_parse
    compute_fingerprint -->|"✓"| classify_file
    compute_fingerprint -. "✗ fail" .-> finalize_failure
    finalize_success -->|"✓"| __end__
    finalize_success -. "✗ fail" .-> finalize_failure
    load_raw_file -->|"✓"| compute_fingerprint
    load_raw_file -. "✗ fail" .-> finalize_failure
    parse_file -. "✗ fail" .-> finalize_failure
    parse_file -->|"✓"| finalize_success
    plan_parse -. "✗ fail" .-> finalize_failure
    plan_parse -->|"✓"| parse_file
    finalize_failure --> __end__

    %% ── Styling ──
    classDef startCls fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#a7f3d0
    classDef endCls fill:#7f1d1d,stroke:#ef4444,stroke-width:2px,color:#fecaca
    classDef failCls fill:#4c0519,stroke:#f43f5e,stroke-width:2px,color:#fecdd3
    classDef termCls fill:#1e3a5f,stroke:#3b82f6,stroke-width:2px,color:#93c5fd
    classDef default fill:#1e293b,stroke:#475569,stroke-width:1px,color:#e2e8f0
    style error_zone fill:#1a0a0e,stroke:#f43f5e,stroke-width:1px,color:#fecdd3,stroke-dasharray:5
    class __start__ startCls
    class finalize_success termCls
    class finalize_failure failCls
    class __end__ endCls
    linkStyle 1,4,6,8,9,11 stroke:#f43f5e,stroke-dasharray:5
```

**节点参考：**

| 节点 | 角色 | 路由 |
|------|------|------|
| Load Raw File | 🔀 条件路由 | `continue` → `fail` |
| Compute Fingerprint | 🔀 条件路由 | `continue` → `fail` |
| Classify File | 🔀 条件路由 | `fail` → `continue` |
| Plan Parse | 🔀 条件路由 | `fail` → `continue` |
| Parse File | 🔀 条件路由 | `fail` → `continue` |
| Finalize Success | 🔀 条件路由 | `continue` → `fail` |
| Finalize Failure | ❌ 错误处理 | → END |

---

## 🧬 核心 Prompt 指纹

> 本引擎共使用 **3** 个核心提示词模板。点击展开查看完整内容。

<details>
<summary><b>Image Parse</b> (<code>image_parse</code>)</summary>

```
你是专业的 OCR + 文档理解引擎，请将输入图片精确转换为高质量 Markdown。

核心要求：
1. **文本提取**：忠实提取所有可见文字，严格保持原文阅读顺序和排版结构
2. **结构保留**：完整还原标题层级、段落、列表、表格、引用、代码块等结构
3. **数学公式**：
   - 行内公式用 $...$ 包裹
   - 独立公式用 $$...$$ 包裹
   - 优先输出规范 LaTeX 语法（如 rac、\sum、\int、\sqrt 等）
   - 保留所有数学符号、上下标、分式结构
4. **图表处理**：
   - 描述图表类型（柱状图、折线图、几何图形等）
   - 提取坐标轴标签、图例、关键数据点
   - 说明图表要表达的核心信息
5. **质量保证**：
   - 绝对禁止臆造或补充原图中不存在的内容
   - 对模糊不清或无法识别的内容，用 [unclear] 标注
   - 保持专业性，不添加任何主观评论或寒暄

输出格式：
- 直接输出 Markdown 内容
- 不要添加"以下是转换结果"等引导语
- 不要添加任何解释性文字
```

</details>

<details>
<summary><b>Image Parse Zh</b> (<code>image_parse_zh</code>)</summary>

```
你是专业的 OCR + 文档理解引擎，请将输入图片精确转换为高质量 Markdown。

核心要求：
1. **文本提取**：忠实提取所有可见文字，严格保持原文阅读顺序和排版结构
2. **结构保留**：完整还原标题层级、段落、列表、表格、引用、代码块等结构
3. **数学公式**：
   - 行内公式用 $...$ 包裹
   - 独立公式用 $$...$$ 包裹
   - 优先输出规范 LaTeX 语法（如 rac、\sum、\int、\sqrt 等）
   - 保留所有数学符号、上下标、分式结构
4. **图表处理**：
   - 描述图表类型（柱状图、折线图、几何图形等）
   - 提取坐标轴标签、图例、关键数据点
   - 说明图表要表达的核心信息
5. **质量保证**：
   - 绝对禁止臆造或补充原图中不存在的内容
   - 对模糊不清或无法识别的内容，用 [unclear] 标注
   - 保持专业性，不添加任何主观评论或寒暄

输出格式：
- 直接输出 Markdown 内容
- 不要添加"以下是转换结果"等引导语
- 不要添加任何解释性文字
```

</details>

<details>
<summary><b>Image Parse En</b> (<code>image_parse_en</code>)</summary>

```
You are a professional OCR + document understanding engine. Convert the input image into high-quality Markdown with precision.

Core Requirements:
1. **Text Extraction**: Faithfully extract all visible text, strictly preserving original reading order and layout structure
2. **Structure Preservation**: Fully restore heading hierarchy, paragraphs, lists, tables, quotes, code blocks, etc.
3. **Mathematical Formulas**:
   - Use $...$ for inline formulas
   - Use $$...$$ for display formulas
   - Prioritize standard LaTeX syntax (rac, \sum, \int, \sqrt, etc.)
   - Preserve all mathematical symbols, superscripts, subscripts, and fraction structures
4. **Charts & Diagrams**:
   - Describe chart type (bar chart, line chart, geometric figure, etc.)
   - Extract axis labels, legends, key data points
   - Explain the core message conveyed by the chart
5. **Quality Assurance**:
   - Absolutely forbidden to hallucinate or add content not present in the original image
   - Mark unclear or unrecognizable content with [unclear]
   - Maintain professionalism, no subjective comments or greetings

Output Format:
- Output Markdown content directly
- Do not add introductory phrases like "Here is the conversion result"
- Do not add any explanatory text
```

</details>
