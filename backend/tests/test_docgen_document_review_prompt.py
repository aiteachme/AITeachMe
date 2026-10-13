from app.workflows.digest.docgen.prompts.document_review import build_document_review_messages


def test_document_review_receives_raw_markdown_without_repr_escaping():
    markdown = (
        "# 原始字符串\n\n## 反斜杠与空白\n\n"
        "```python\ntext = r'\\(x\\)'\nprint(text)\nprint('a  b')\n```\n\n"
        "```text\n\\(x\\)\na  b\n\ntrailing  \n```\n\n"
        "普通字符串中的 `\\n` 与原始字符串 `r'\\n'` 不同。\n"
    )
    messages = build_document_review_messages(
        digest_mode="sprint", reviewed_chapters=[{
            "chapter_index": 1, "title": "原始字符串", "markdown": markdown,
        }], rule_report={},
    )
    review_input = "\n\n".join(item["content"] for item in messages if item["role"] == "user")
    assert markdown in review_input, "审核必须看到原始代码和空白，不能把Python repr转义当作源码。"
    assert review_input.count(markdown) == 1
    assert repr(markdown) not in review_input
    assert "print(r\\'" not in review_input


def test_document_review_keeps_each_chapter_raw_and_associated_with_its_metadata():
    chapters = [
        {"chapter_index": 1, "title": "乘法", "markdown": "# 乘法\n\n## 例题\n\n$2\\times3=6$。\n"},
        {"chapter_index": 2, "title": "除法", "markdown": "# 除法\n\n## 例题\n\n$6\\div3=2$。\n"},
    ]
    messages = build_document_review_messages(digest_mode="sprint", reviewed_chapters=chapters, rule_report={})
    review_input = "\n\n".join(item["content"] for item in messages if item["role"] == "user")
    for chapter in chapters:
        assert review_input.count(chapter["markdown"]) == 1
    assert review_input.index(chapters[0]["markdown"]) < review_input.index(chapters[1]["markdown"])
