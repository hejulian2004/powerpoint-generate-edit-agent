"""Unit tests for Markdown & Plain-Text Outline Parsing (PR13 Step 2)."""

from backend.pptspec.parser import InputFormat, detect_format
from backend.pptspec.normalizer import normalize_presentation_input
from backend.presentation.schema import SlideType


def test_markdown_presentation_outline():
    markdown_text = """
# AnomalyAgent: 智能运维多智能体架构

## Slide 1: 研究背景与挑战
- 云原生系统微服务规模庞大，指标维度极高
- 传统规则告警误报率高达 45%
- 引入多智能体协同排障机制

## Slide 2: 整体架构设计
- 详见论文架构图 Figure 3，位于论文第 5 页
- 包含感知智能体、定位智能体、根因分析智能体
- 智能体间通过事件总线通信

## Slide 3: 实验性能对比
| 方法 | 准确率 | F1 分数 |
| 传统基线 | 76.4% | 0.742 |
| SOTA (2023) | 81.2% | 0.798 |
| Ours (AnomalyAgent) | 89.5% | 0.884 |
"""

    fmt = detect_format(markdown_text)
    assert fmt == InputFormat.MARKDOWN

    res = normalize_presentation_input(markdown_text, strict_truthfulness=True)
    assert res.valid is True
    assert res.spec is not None
    assert len(res.spec.slides) == 3
    assert res.summary["figures"] == 1
    assert res.summary["complete_tables"] == 1

    # Check Slide 2 has Figure 3 reference
    fig_reqs = [r for r in res.asset_requirements if r.asset_type == "figure"]
    assert len(fig_reqs) == 1
    assert "Figure 3" in fig_reqs[0].label
    assert fig_reqs[0].page == 5


def test_chinese_plain_text_outline():
    chinese_text = """
第1页：研究背景
- 传统人工排障效率低
- 业务故障平均修复时间 MTTR 高达 120 分钟

第2页：方法概览
- 架构设计见 Figure 2，第 4 页
- 核心协同决策模型

第3页：消融实验
- Table 2 展示了不同组件剥离对性能的影响，参见论文第 8 页
- 移除多轮协同后性能下降
"""

    res = normalize_presentation_input(chinese_text, strict_truthfulness=True)
    assert res.valid is True
    assert res.spec is not None
    assert len(res.spec.slides) == 3

    # Verify slide types mapped from Chinese keywords
    assert res.spec.slides[0].type == SlideType.BACKGROUND
    assert res.spec.slides[1].type == SlideType.METHOD_OVERVIEW
    assert res.spec.slides[2].type == SlideType.ABLATION

    # Check asset requirements: Figure 2 and Table 2 (placeholder table)
    reqs = res.asset_requirements
    assert len(reqs) == 2
    assert any(r.asset_type == "figure" and "Figure 2" in r.label for r in reqs)
    assert any(r.asset_type == "table" and "Table 2" in r.label for r in reqs)
