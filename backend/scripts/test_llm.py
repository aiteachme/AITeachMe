#!/usr/bin/env python3
"""
测试 llm.py 三种调用方式：acompletion / acompletion_structured / acompletion_stream
用法: cd backend && python -m scripts.test_llm
"""
import asyncio
import sys
import time

from pydantic import BaseModel, Field
from app.schemas.llm import ChatMessage, USER


async def test_acompletion() -> None:
    """测试普通异步补全"""
    from app.core.llm import acompletion

    print("=" * 60)
    print("1️⃣  测试 acompletion() — 异步补全")
    print("=" * 60)

    messages = [ChatMessage(role=USER, content="用一句话解释什么是递归")]
    start = time.monotonic()
    try:
        result = await acompletion(messages, max_tokens=200)
        elapsed = time.monotonic() - start
        print(f"  ✅ 成功 ({elapsed:.2f}s)")
        print(f"  回复: {result}")
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"  ❌ 失败 ({elapsed:.2f}s): {e}")


class CityInfo(BaseModel):
    """用于测试结构化输出的模型"""
    name: str = Field(description="城市名称")
    country: str = Field(description="所属国家")
    population_million: float = Field(description="人口（百万）")
    famous_for: str = Field(description="以什么闻名")


async def test_acompletion_structured() -> None:
    """测试 Instructor 结构化输出"""
    from app.core.llm import acompletion_structured

    print()
    print("=" * 60)
    print("2️⃣  测试 acompletion_structured() — 结构化输出")
    print("=" * 60)

    messages = [ChatMessage(role=USER, content="介绍一下东京这座城市")]
    start = time.monotonic()
    try:
        result = await acompletion_structured(
            response_model=CityInfo,
            messages=messages,
            max_tokens=300,
        )
        elapsed = time.monotonic() - start
        print(f"  ✅ 成功 ({elapsed:.2f}s)")
        print(f"  类型: {type(result).__name__}")
        print(f"  name: {result.name}")
        print(f"  country: {result.country}")
        print(f"  population_million: {result.population_million}")
        print(f"  famous_for: {result.famous_for}")
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"  ❌ 失败 ({elapsed:.2f}s): {e}")


async def test_acompletion_stream() -> None:
    """测试流式输出"""
    from app.core.llm import acompletion_stream

    print()
    print("=" * 60)
    print("3️⃣  测试 acompletion_stream() — 流式输出")
    print("=" * 60)

    messages = [ChatMessage(role=USER, content="用三句话介绍Python语言")]
    start = time.monotonic()
    try:
        print("  输出: ", end="", flush=True)
        token_count = 0
        async for token in acompletion_stream(messages, max_tokens=200):
            print(f"|{token}|", end="", flush=True)
            token_count += 1
        elapsed = time.monotonic() - start
        print()
        print(f"  ✅ 成功 ({elapsed:.2f}s, {token_count} chunks)")
    except Exception as e:
        elapsed = time.monotonic() - start
        print()
        print(f"  ❌ 失败 ({elapsed:.2f}s): {e}")


async def main() -> None:
    from app.core.config import get_settings
    settings = get_settings()

    print()
    print("📋 当前配置")
    print(f"  LLM_MODEL  : {settings.llm_model}")
    print(f"  LLM_BASE_URL: {settings.llm_base_url}")
    print()

    await test_acompletion()
    await test_acompletion_structured()
    await test_acompletion_stream()

    print()
    print("=" * 60)
    print("🏁 全部测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
