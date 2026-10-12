"""Shared presentation contract for chapter-end test planning and review."""

UNIT_TEST_PRESENTATION_CONTRACT = (
    "章末测验的固定发布协议：每题使用独立的 [!QUESTION]，紧跟对应的 [!ANSWER]，"
    "答案和完整解析只放在 ANSWER 块中。网页默认折叠 ANSWER，点击才展示，"
    "因此 Markdown 源码中逐题相邻不代表提前向学生泄漏答案。"
    "不要额外发明‘全部题目之后集中放答案’的硬约束，也不要仅因逐题配对而要求调整答案布局。"
    "用户要求独立作答、答案分离或不泄漏答案时，使用上述折叠协议落实。"
    "上游自动简报里的布局建议不能覆盖此协议；题型、数量、题干条件和答案正确性仍须严格核验。"
)
