## 十一、开放问题（需要确认）

> [!IMPORTANT]
> 以下问题将直接影响代码实现路径，请逐条确认：

### 11.1 模型与 API 相关

1. **文生图模型选择**：通义万相 (Wanxiang) 还是 Qwen-VL？前者更适合生成"教学配图"（如函数图像、几何示意图），后者更适合多模态理解。或者用 Gemini Flash Image（gpt-researcher 默认）？
   - 建议：MVP 阶段用通义万相（DashScope 生态内，API 统一），V2 再考虑 Gemini。

2. **Strategic LLM 选择**：`qwq-32b`（推理能力强但慢）还是 `qwen-max`（快但推理稍弱）？
   - 建议：默认 `qwq-32b`，配置可切换。

3. **Bing Search API Key**：是否已有？需要申请 Azure Cognitive Services 的 Bing Search v7。
   - 备选：博查搜索（国内 AI 搜索，中文效果好）。

### 11.2 文档模式相关

4. **速成课章节数是否可配置**：当前设计锁死 4 节。是否需要用户可选 3-6 节？
   - 建议：MVP 锁死 4 节，V2 开放配置。

5. **系统课字数目标**：当前设计 10000-15000 字。是否需要更精确的控制（如用户可输入目标字数）？
   - 建议：MVP 用 `edu_planner` 的 `writing_instructions` 控制，不暴露给用户。

6. **语言风格是否暴露给用户**：`tone` 参数（casual/professional/encouraging/concise）是否在前端提供选择？
   - 建议：MVP 速成课默认 casual，系统课默认 professional。V2 开放选择。

7. **速成课/系统课是否需要更严格的格式模板**：比如速成课每节必须有"速记卡"，系统课每节必须有"前置知识"？
   - 建议：是的，通过 Prompt 硬性约束（已在 4.5 节设计）。

### 11.3 检索与资源相关

8. **本地教育语料库的初始范围**：先覆盖哪些学科？
   - 建议：MVP 先覆盖高等数学（微积分、线性代数、概率论），这是用户量最大的场景。

9. **蜂考等商业素材的合规处理**：是否可以用 AI 重新组织为自己的知识条目？
   - 建议：可以，但必须满足：① 不存储原文 ② 用 AI 重新组织 ③ 标注"参考来源"而非"引用来源"。需要法务确认。

10. **检索结果是否需要缓存**：同一个 query 短时间内重复搜索是否走缓存？
    - 建议：是的，用 Redis 或内存缓存，TTL 1 小时。

### 11.4 前端与交互相关

11. **交互式 HTML（`[INTERACTIVE: ...]`）是否在 MVP 阶段支持**：实现复杂度较高（需要沙箱 + iframe）。
    - 建议：MVP 不支持，占位符降级为文字描述。V2 支持。

12. **文档导出格式**：除了前端渲染，是否需要导出为 PDF / DOCX？
    - 建议：MVP 只支持前端渲染 + Markdown 下载。V2 支持 PDF 导出（Mermaid 需要预渲染为 SVG）。

13. **文档版本管理**：同一主题重新生成文档时，是覆盖还是保留历史版本？
    - 建议：保留历史版本，前端展示最新版，可切换查看历史。

### 11.5 其他 Deep Research 框架调研

14. **是否需要调研其他框架**：除了 gpt-researcher，还有一些值得关注的：
    - [STORM (Stanford)](https://github.com/stanford-oval/storm) — 学术论文级别的研究报告生成，有 Wikipedia 风格的多视角写作
    - [Tavily Research](https://tavily.com) — 专注搜索质量的 API
    - [Perplexity-style](https://github.com/rashadphz/farfalle) — 开源 Perplexity 克隆
    - 建议：当前 gpt-researcher 的 Plan-Execute 范式已经足够，其他框架可作为 V2 参考。

15. **教育领域专属工具/API 调研**：
    - [Wolfram Alpha API](https://products.wolframalpha.com/api/) — 数学计算验证
    - [Mathpix](https://mathpix.com/) — OCR 识别手写公式
    - [Khan Academy API](https://www.khanacademy.org/) — 教育内容（但 API 有限）
    - 建议：Wolfram Alpha 可在 V2 集成，用于验证生成的公式是否正确。

---
