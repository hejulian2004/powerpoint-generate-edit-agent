"""Unit tests for Context Accounting, 90% Threshold Auto-Compression, and Indicator Logic."""

import pytest
from backend.agent.context_compressor import (
    estimate_tokens,
    estimate_messages_tokens,
    ContextCompressor,
    ContextUsageReport,
    AUTO_COMPRESSION_THRESHOLD
)


def test_token_estimator_logic():
    """Verify mixed CJK and English token estimation."""
    # Empty string
    assert estimate_tokens("") == 0

    # Short English
    eng_tokens = estimate_tokens("Hello World")
    assert eng_tokens > 0

    # Chinese string ~ 1.6 tokens per char
    cn_text = "基于深度学习的幻灯片生成与排版优化"  # 17 chars -> ~27 tokens
    cn_tokens = estimate_tokens(cn_text)
    assert 20 <= cn_tokens <= 35


def test_context_compressor_healthy_under_90_percent():
    """Verify that when token usage is below 90%, no compression is performed."""
    messages = [
        {"role": "system", "content": "You are PPT-Agent assistant."},
        {"role": "user", "content": "请生成关于人工智能的介绍"},
        {"role": "assistant", "content": "已为您规划 3 页大纲"}
    ]
    # Limit: 256K tokens (healthy usage << 90%)
    compressed, report = ContextCompressor.evaluate_and_compress(
        messages=messages,
        max_tokens=256 * 1024,
        context_key="256k"
    )

    assert report.is_compressed is False
    assert report.usage_percent < 10.0
    assert report.threshold_reached is False
    assert len(compressed) == len(messages)


def test_context_compressor_triggers_at_90_percent_threshold():
    """Verify that when token usage hits >= 90%, sliding-window auto-compression triggers."""
    # Create an artificial low budget (e.g. 500 tokens) and populate messages exceeding 450 tokens (90%)
    messages = [
        {"role": "system", "content": "System prompt for PPT agent with initial design rules."}
    ]
    for i in range(10):
        messages.append({"role": "user", "content": f"用户历史指令第 {i+1} 轮：请调整排版边距与字体颜色，增加留白呼吸感，同时优化卡片圆角。"})
        messages.append({"role": "assistant", "content": f"架构师第 {i+1} 轮答复：已自动调用 update_element 优化图元坐标与样式属性。"})

    total_tokens_before = estimate_messages_tokens(messages)
    # Set a budget where current tokens exceed 90%
    budget = int(total_tokens_before / 0.95)  # ~95% usage

    compressed, report = ContextCompressor.evaluate_and_compress(
        messages=messages,
        max_tokens=budget,
        context_key="custom"
    )

    # 1. Verification: compression was triggered
    assert report.is_compressed is True
    assert report.tokens_saved > 0
    assert len(compressed) < len(messages)

    # 2. Structure of compressed messages:
    # System message preserved, followed by summary anchor, followed by recent messages
    assert compressed[0]["role"] == "system"
    anchor = compressed[1]
    assert "历史上下文自动压缩摘要" in anchor["content"]
    assert "因达到上下文窗口 90% 阈值已归档" in anchor["content"]

    # 3. Recent messages preserved
    assert compressed[-1]["content"] == messages[-1]["content"]
