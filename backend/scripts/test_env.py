#!/usr/bin/env python3
"""
测试 .env 配置：验证 API Key、LLM 模型、Embedding 模型是否可用。
用法: cd backend && python -m scripts.test_env
"""
import asyncio
import time

import litellm


async def main() -> None:
    # 加载配置
    from app.shared.infra.settings import get_settings
    from app.shared.infra.env_support import get_env
    from app.shared.infra.llm_support.common import build_litellm_provider_kwargs
    from app.shared.infra.settings.support import (
        llm_provider_requires_api_key,
        resolve_runtime_llm_provider,
    )

    settings = get_settings()
    llm_base_url = get_env("LLM_BASE_URL") or ""
    llm_provider = resolve_runtime_llm_provider(base_url=llm_base_url)
    llm_api_key = (get_env("LLM_API_KEY") or "").strip() or None
    key_required = llm_provider_requires_api_key(llm_provider, base_url=llm_base_url)

    print("=" * 60)
    print("📋 当前 .env 配置")
    print("=" * 60)
    print(f"  LLM_PROVIDER      : {llm_provider}")
    print(f"  LLM_BASE_URL      : {llm_base_url}")
    print(f"  LLM_MODEL         : {settings.models.primary}")
    print(f"  EMBEDDING_MODEL   : {settings.models.embedding}")
    print(f"  EMBEDDING_DIM     : {settings.embedding_dim}")
    if llm_api_key:
        print(f"  LLM_API_KEY       : {llm_api_key[:8]}...{llm_api_key[-4:]}")
    else:
        print(f"  LLM_API_KEY       : {'未配置（当前 provider 可省略）' if not key_required else '未配置'}")
    print()

    if key_required and not llm_api_key:
        print("❌ 当前 provider 需要 API Key，但未配置 `LLM_API_KEY`。")
        return

    # ---------- 测试 LLM ----------
    print("=" * 60)
    print("🧠 测试 LLM 模型")
    print("=" * 60)
    try:
        start = time.monotonic()
        llm_kwargs = {
            "model": settings.models.primary,
            messages=[{"role": "user", "content": "用一句话介绍你自己"}],
            max_tokens=100,
            **build_litellm_provider_kwargs(settings.models.primary),
        }
        if llm_base_url:
            llm_kwargs["api_base"] = llm_base_url
        if llm_api_key is not None:
            llm_kwargs["api_key"] = llm_api_key
        response = await litellm.acompletion(**llm_kwargs)
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
    embedding_model = str(settings.models.embedding or "").strip()
    if not embedding_model:
        print("  ⏭️  已跳过：当前 provider 默认未配置 embedding 模型。")
    else:
        try:
            start = time.monotonic()
            embedding_kwargs = {
                "model": embedding_model,
                "input": ["这是一段测试文本，用于验证 embedding 模型是否正常工作。"],
                **build_litellm_provider_kwargs(embedding_model),
            }
            if llm_base_url:
                embedding_kwargs["api_base"] = llm_base_url
            if llm_api_key is not None:
                embedding_kwargs["api_key"] = llm_api_key
            response = await litellm.aembedding(**embedding_kwargs)
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
