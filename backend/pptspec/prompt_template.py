"""Prompt Templates for External AI PPT Planning (PR13).

Provides prompts to guide external LLMs (ChatGPT, Claude, Gemini, Qwen, etc.)
to analyze papers and generate structured PPT plans without hallucinating facts.
"""

from __future__ import annotations

import json
from .schema import CanonicalPPTSpec


def get_general_prompt() -> str:
    """General, flexible prompt focusing on factual preservation."""
    return """你是一位顶尖的学术论文分析与演示文稿策划专家。请仔细阅读并分析这篇学术论文，为学术组会（15分钟汇报）输出结构化的 PPT 汇报大纲与内容规划。

【核心原则 - 严禁捏造任何事实】:
1. 真实性第一：PPT 中出现的所有数字（如准确率、F1、延迟、显存占用、提升比例等）必须 100% 摘自论文原文，严禁猜测或编造任何实验数据。
2. 图表占位机制：
   - 论文原图（Figure）：只需指出图编号、Caption说明和论文页码（例如：“Figure 3, Page 5, Overall Architecture”）。不要尝试用字符重画，PPT 系统会自动生成高保真占位框，供作者后续直接粘贴原图。
   - 论文表格（Table）：如果表格数据完整且重要，请给出完整的表头与全部行数据；如果数据不完整或表格过大，只需给出 Table 编号与主要结论，系统会为其预留占位区域，绝对不要擅自补齐虚构的行或数字。
3. 缺失信息直接省略或明确注明未知，不要使用常识补全未提及的基线方法或超参数。

【推荐输出结构】:
请优先使用 Markdown 或标准 JSON 输出，包含以下内容：
- 汇报基本信息（论文标题、作者、发表会议/期刊、目标受众、汇报时长约15分钟）
- 核心证据列表（包含关键结论 Claim、核心指标 Metric、引用的 Figure 编号及页码、表格数据 Table）
- 逐页幻灯片规划（建议 10~15 页）：
  * 标题 (Title) 与幻灯片类型 (TITLE, BACKGROUND, PROBLEM, METHOD_OVERVIEW, METHOD_DETAIL, RESULT, CONCLUSION 等)
  * 该页目标 (Objective)
  * 引用的证据项 (Evidence)
  * 要点展示列表 (Bullets)
  * 演讲者备注 (Speaker Notes)

请开始分析论文并输出汇报规划方案：
""".strip()


def get_strict_prompt() -> str:
    """Strict JSON prompt with CanonicalPPTSpec JSON schema attached."""
    schema_dict = CanonicalPPTSpec.model_json_schema()
    schema_json = json.dumps(schema_dict, indent=2, ensure_ascii=False)

    return f"""你是一位学术 PPT 结构化编译器。请分析论文内容，并将汇报规划直接输出为符合以下 JSON Schema 的严格 JSON 对象。

【不可违背的事实约束】:
1. 严禁捏造任何实验数值，所有数字必须直接摘自论文原文。
2. Figure 仅填写 figure_reference 证据（label, caption, source_page），严禁伪造图片数据。
3. Table 必须保证 rows 每一行的元素个数与 columns 长度完全相等；若数据不全，请不要填充伪造数据。
4. 每页 slide 的 evidence_refs 必须引用在 evidence 数组中真实声明的 id。
5. 只输出纯 JSON 字符串（可以用代码块包裹），不要包含其他冗余废话。

【目标 JSON Schema】:
```json
{schema_json}
```

请依据上述 Schema 输出合法的学术 PPT 规划 JSON：
""".strip()
