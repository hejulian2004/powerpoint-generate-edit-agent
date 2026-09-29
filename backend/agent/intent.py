"""Intent labels for the slide agent.

The model is the only classifier. This module parses its JSON decision and
does not keep a keyword table.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from ..ir.models import PresentationIR

logger = logging.getLogger(__name__)

VALID_INTENTS = {
    "generate_presentation",
    "generate_slide",
    "modify_elements",
    "optimize_layout",
    "apply_theme",
    "undo",
    "chat",
}

ROUTER_SYSTEM_PROMPT = """你是一个专业的 PPT 演示文稿智能助手意图路由分类器。
你的唯一任务是：分析用户的输入指令，结合当前演示文稿的状态，将用户的真实意图精确分类到以下 7 种标准意图之一：

1. "generate_presentation": 用户希望生成整套多页 PPT 演示文稿（例如：“制作一份关于...的PPT”、“根据大纲生成文稿”、“写一个商业计划书PPT”）。
2. "generate_slide": 用户希望新建一页幻灯片（如“新增一页”、“加一页空白幻灯片”），或在当前页生成特定版式架构块（如“生成时间线”、“添加KPI指标卡”、“生成两栏对比”、“做三张特性卡片”）。
3. "modify_elements": 用户希望对当前页面的具体图元/文字进行局部微调（如“把标题改成XX”、“文字变大一点”、“背景矩形换成红色”、“删掉这个卡片”、“往右移动50px”）。
4. "optimize_layout": 用户希望对页面进行美化、UI优化、排版重构、消除重叠/遮挡、自动对齐规整、呼吸感留白调整（例如：“美化ui”、“美化界面”、“美化一下”、“优化排版”、“页面太挤了整理一下”、“自动排版”、“排版美化”、“好看一点”）。
5. "apply_theme": 用户希望切换或应用全局配色/设计主题（例如：“换成深色主题”、“改成科技蓝风格”、“换成极简黑曜风格”）。
6. "undo": 用户希望撤销上一轮操作、回退修改（例如：“撤销”、“回退刚才的修改”、“undo”）。
7. "chat": 纯闲聊、打招呼、提问咨询、与 PPT 设计/排版/生成完全无关的问答（例如：“你好”、“你叫什么名字”、“什么是中间表示”、“介绍一下你自己”）。

【输出规范】:
请严格输出合法的 JSON 对象，不要输出任何额外文本：
{
  "intent": "<上述7种意图之一>",
  "reason": "<简明判定理由>"
}
"""


def _extract_intent_from_response(content: str) -> Optional[str]:
    """Extracts a valid intent string from an LLM JSON response."""
    if not content or not content.strip():
        return None
    try:
        data = json.loads(content.strip())
        if isinstance(data, dict):
            cand = str(data.get("intent") or "").strip()
            if cand in VALID_INTENTS:
                return cand
    except Exception:
        pass
    match = re.search(r'["\']intent["\']\s*:\s*["\']\s*([a-zA-Z_]+)\s*["\']', content)
    if match and match.group(1) in VALID_INTENTS:
        return match.group(1)
    return None


async def classify_intent_with_llm(
    llm_client: Any,
    user_query: str,
    pres: Optional[PresentationIR],
) -> Optional[str]:
    """Ask the model which intent applies. A missing or invalid answer is not a guess."""
    if not llm_client or not hasattr(llm_client, "chat_completion"):
        return None

    context_lines = [f"用户输入: \"{user_query}\""]
    if pres and pres.slides:
        context_lines.append(f"当前演示文稿状态: 共 {len(pres.slides)} 页，标题: 《{pres.title or '未命名'}》")
        active = pres.get_active_slide()
        if active:
            context_lines.append(
                f"当前停留页: 第 {active.slide_num} 页 (ID: {active.id})，包含 {len(active.elements)} 个元素"
            )
    else:
        context_lines.append("当前演示文稿状态: 空文稿 (0页)")

    try:
        resp = await llm_client.chat_completion(
            messages=[
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(context_lines)},
            ],
            role="fast",
            temperature=0.0,
            max_tokens=150,
        )
        content = ""
        if isinstance(resp, dict):
            choices = resp.get("choices") or []
            if choices:
                content = choices[0].get("message", {}).get("content", "")
        if content:
            parsed = _extract_intent_from_response(content)
            if parsed:
                return parsed
    except Exception as exc:
        logger.warning(f"LLM intent classification failed: {exc}")
    return None
