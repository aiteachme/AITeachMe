#!/usr/bin/env python3
"""
测试 .env 配置：验证 API Key、LLM 模型、Embedding 模型是否可用。
用法: cd backend && python -m scripts.test_env
"""
import asyncio
import sys
import time

import litellm


async def main() -> None:
    # 加载配置
    from app.core.config import get_settings

    settings = get_settings()

    print("=" * 60)
    print("📋 当前 .env 配置")
    print("=" * 60)
    print(f"  LLM_BASE_URL      : {settings.llm_base_url}")
    print(f"  LLM_MODEL         : {settings.llm_model}")
    print(f"  EMBEDDING_MODEL   : {settings.embedding_model}")
    print(f"  EMBEDDING_DIM     : {settings.embedding_dim}")
    print(f"  LLM_API_KEY       : {settings.llm_api_key[:8]}...{settings.llm_api_key[-4:]}")
    print()

    # ---------- 测试 LLM ----------
    print("=" * 60)
    print("🧠 测试 LLM 模型")
    print("=" * 60)
    try:
        start = time.monotonic()
        response = await litellm.acompletion(
            model=f"openai/{settings.llm_model}",
            messages=[{"role": "user", "content": "用一句话介绍你自己"}],
            api_base=settings.llm_base_url,
            api_key=settings.llm_api_key,
            max_tokens=100,
        )
        elapsed = time.monotonic() - start

        content = response.choices[0].message.content
        usage = response.usage
        print(f"  ✅ 调用成功 ({elapsed:.2f}s)")
        print(f"  模型回复  : {content}")
        print(f"  Token 用量: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}")
    except Exception as e:
        print(f"  ❌ 调用失败: {e}")

    print()

    # ---------- 测试 Embedding ----------
    print("=" * 60)
    print("📐 测试 Embedding 模型")
    print("=" * 60)
    try:
        start = time.monotonic()
        response = await litellm.aembedding(
            model=f"openai/{settings.embedding_model}",
            input=["这是一段测试文本，用于验证 embedding 模型是否正常工作。"],
            api_base=settings.llm_base_url,
            api_key=settings.llm_api_key,
        )
        elapsed = time.monotonic() - start

        vector = response.data[0]["embedding"]
        usage = getattr(response, "usage", None)
        print(f"  ✅ 调用成功 ({elapsed:.2f}s)")
        print(f"  向量维度  : {len(vector)}")
        print(f"  前5个值   : {vector[:5]}")
        if usage:
            print(f"  Token 用量: {usage.total_tokens}")

        # 维度校验
        if len(vector) != settings.embedding_dim:
            print(f"  ⚠️  实际维度 {len(vector)} ≠ 配置维度 {settings.embedding_dim}，需更新 _EMBEDDING_DIM_MAP!")
        else:
            print(f"  ✅ 维度匹配 ({settings.embedding_dim})")
    except Exception as e:
        print(f"  ❌ 调用失败: {e}")

    print()
    print("=" * 60)
    print("🏁 测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
