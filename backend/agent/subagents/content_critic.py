"""Independent Content & Structure Critic Subagent (Blind Content Auditor).

Specializes STRICTLY in textual and structural inspection:
- Verifies clarity, conciseness, bullet-point brevity (no walls of text).
- Checks narrative consistency, logical arguments, and conclusion validity.
- DOES NOT touch layout coordinates, rendering, shapes, or visual aesthetics.
- Visual Critic is thus liberated to focus purely on geometry, spacing, alignment, and aesthetic beauty.
"""

from __future__ import annotations
import inspect
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, List
from ...ir.models import SlideIR, TextElementIR

logger = logging.getLogger(__name__)

CONTENT_CRITIC_SYSTEM_PROMPT = """你是一位完全独立、严苛客观的第三方 PPT 内容与叙事结构总监（Content Critic Subagent）。
你受聘对主创设计的幻灯片文案、信息结构与格式规范进行客观盲审。你不知道主创的构思历史或交谈上下文，仅从读者汲取信息效率和工程格式规范的角度严格审查。

【评审核心准则（专注于文字结构与格式合规，绝不评审视觉排版）】:
1. 标签闭合与格式合法性（一票否决项）:
   - 检查文本中是否残留未闭合的伪标签（如 `<b>`, `<strong>`, `<span>`, `<font>`, `<color>`, `</...>` 等 HTML/XML 标签缺失闭合）。
   - 检查是否遗留未闭合的成对符号（如未成对的书名号《》、括号（）、引号""、“”、中括号[]、花括号{}）。
   - 检查是否含有未解析的原始模板插值符或格式破坏占位（如 `${...}`, `{{...}}`, `<unclosed>`）。
2. 文字精炼度（铁律）：严禁大段拥挤的长篇大论（单条正文建议 <= 25 字），必须提炼为高信息密度的短语、结论或数据指标。
3. 观点与结论明确性：标题与正文是否有清晰的论断，是否是"观点先行"而非陈述流水账。
4. 术语与中文规范：以规范中文表述为主，专业术语翻译得当，避免中英文夹杂错乱。
5. 信息结构清晰度：是否有鲜明的主标、副标、要点层级，条目数量是否适度（3~4 条最佳）。

【输出格式要求】:
请严格保持客观、理性、文字编辑与格式专家的批判口吻，输出以下格式：
【文案优点】: 简述 1 点文字表达优势
【格式与标签诊断】: 指出是否存在未闭合标签/符号或格式违规（若格式合规标明"格式与标签完好闭合"）
【文字冗余诊断】: 指出 1~2 处啰嗦长句、概念模糊或需要精炼的地方（若无冗余注明精炼达标）
【精炼修改建议】: 给出 1~2 条具体的文案提炼或标签修复建议
【内容评审结论】: 通过 / 需修正（两者选一，若存在未闭合标签或严重格式硬伤必须判定为"需修正"）
【内容健康分: XX/100】（0-100的整数分：精炼规范85-95，尚可70-84，存在标签/格式硬伤或严重冗长堆砌<70）
"""


@dataclass
class ContentCriticResult:
    """Consolidated outcome of the independent Content Critic Subagent."""
    approved: bool
    score: float
    summary: str
    strengths: str
    redundancy_issues: List[str]
    recommendations: List[str]
    needs_content_refinement: bool
    subagent_info: Dict[str, Any] = field(default_factory=lambda: {
        "subagent_name": "ContentCriticSubagent",
        "context_isolated": True,
        "role": "independent_content_structural_auditor"
    })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "score": self.score,
            "summary": self.summary,
            "strengths": self.strengths,
            "redundancy_issues": self.redundancy_issues,
            "recommendations": self.recommendations,
            "needs_content_refinement": self.needs_content_refinement,
            "subagent_info": self.subagent_info
        }


class ContentCriticSubagent:
    """Independent Content Critic Subagent."""

    @classmethod
    def extract_slide_text_manifest(cls, slide: SlideIR) -> str:
        """Extracts text hierarchy from slide with zero layout distraction."""
        lines = [f"【幻灯片 #{slide.slide_num}（标题: '{slide.title or '未命名'}'）文本内容列表】:"]
        for el in slide.elements:
            if isinstance(el, TextElementIR) and el.text_content and el.text_content.plain_text.strip():
                txt = el.text_content.plain_text.strip()
                lines.append(f"- [ID: '{el.id}'] (字数: {len(txt)}): \"{txt}\"")
        return "\n".join(lines)

    @classmethod
    def check_unclosed_tags_and_formatting(cls, text: str) -> List[str]:
        """Validates that tags, paired delimiters, and formatting placeholders are strictly closed."""
        issues: List[str] = []
        if not text:
            return issues

        # 1. HTML / XML style tag balance check (e.g. <b>, <strong>, <span>, <font>, <color>, etc.)
        # Exclude standard math inequality operators like "x < 5" or "ratio > 2"
        tag_pattern = re.compile(r'<\s*(/)?\s*([a-zA-Z][a-zA-Z0-9_-]*)\b[^>]*?(/)?>')
        stack: List[str] = []

        for m in tag_pattern.finditer(text):
            is_closing = bool(m.group(1))
            tag_name = m.group(2).lower()
            is_self_closing = bool(m.group(3))

            if is_self_closing:
                continue

            if not is_closing:
                stack.append(tag_name)
            else:
                if not stack:
                    issues.append(f"发现多余闭合标签 '</{tag_name}>'，缺少前置开始标签")
                elif stack[-1] == tag_name:
                    stack.pop()
                else:
                    expected = stack.pop()
                    issues.append(f"标签闭合错配: 预期 '</{expected}>'，但遇到 '</{tag_name}>'")

        while stack:
            unclosed = stack.pop()
            issues.append(f"发现未闭合标签 '<{unclosed}>'，必须成对闭合")

        # 2. Check unparsed raw template placeholders like ${var} or {{var}}
        if re.search(r'\$\{[^}]*$', text) or re.search(r'\{\{[^}]*$', text):
            issues.append("发现未闭合的模板占位表达式 (如 '${...' 或 '{{...')")

        # 3. Check asymmetrical paired bracket/quote symbols in professional slide text
        pairs = [
            ("《", "》", "书名号"),
            ("（", "）", "全角括号"),
            ("【", "】", "中括号/方头括号"),
            ("“", "”", "中文双引号"),
        ]
        for open_sym, close_sym, sym_name in pairs:
            c_open = text.count(open_sym)
            c_close = text.count(close_sym)
            if c_open != c_close:
                issues.append(f"{sym_name}未成对闭合 ({open_sym} 出现 {c_open} 次，{close_sym} 出现 {c_close} 次)")

        return issues

    @classmethod
    async def audit_content(
        cls,
        slide: SlideIR,
        llm_client: Optional[Any] = None,
        session_memory: Optional[Any] = None,
        on_event: Optional[Callable] = None
    ) -> ContentCriticResult:
        """Executes the decoupled, context-isolated content audit on a slide with dedicated rework memory."""
        # 1. Broadcast lifecycle start: Main agent pauses
        round_idx = (len(session_memory.entries) + 1) if session_memory else 1
        if on_event:
            await cls._safe_emit(on_event, {
                "type": "subagent_lifecycle",
                "phase": "started",
                "subagent": "ContentCriticSubagent",
                "main_agent_status": "paused_waiting",
                "slide_id": slide.id,
                "round": round_idx,
                "text": "主 Agent 已暂停等候，独立内容结构 Subagent 介入文案精炼度与格式标签盲审..."
            })
            await cls._safe_emit(on_event, {
                "type": "content_critique",
                "status": "evaluating",
                "slide_id": slide.id,
                "text": "独立 Content Subagent 审查文字篇幅、观点凝练、标签闭合与格式规范..."
            })

        # 2. Rule-based pre-scan: check text wall, long sentences, and UNCLOSED TAGS / FORMATS
        text_manifest = cls.extract_slide_text_manifest(slide)
        rule_issues: List[str] = []
        rule_recs: List[str] = []
        has_tag_or_format_defect = False
        base_score = 92.0

        for el in slide.elements:
            if isinstance(el, TextElementIR) and el.text_content:
                txt = el.text_content.plain_text.strip()

                # Check unclosed tags and format violations
                tag_defects = cls.check_unclosed_tags_and_formatting(txt)
                if tag_defects:
                    has_tag_or_format_defect = True
                    base_score -= 30.0  # Heavy penalty for unclosed tags/format breakage
                    for td in tag_defects:
                        rule_issues.append(f"元素 '{el.id}' 格式违规: {td}")
                    rule_recs.append(f"修复元素 '{el.id}' 文本，正确闭合所有标签与符号")

                if len(txt) > 80:
                    base_score -= 15.0
                    rule_issues.append(f"元素 '{el.id}' 单段长达 {len(txt)} 字，存在严重阅读负担。")
                    rule_recs.append(f"提炼元素 '{el.id}' 为核心结论，建议截断或分点拆分。")
                elif len(txt) > 40:
                    base_score -= 5.0
                    rule_issues.append(f"元素 '{el.id}' 句长偏长 ({len(txt)} 字)，建议精炼为小短语。")

        # 3. LLM blind review with strict context isolation
        has_llm = bool(llm_client and getattr(llm_client, "api_key", None) and not str(llm_client.api_key).startswith("mock_"))
        llm_feedback = ""

        if has_llm:
            try:
                rework_context = ""
                if session_memory and session_memory.entries:
                    rework_context = f"\n\n【Subagent 专属历史内容审查记录（对比上一轮文案返工修正）】:\n{session_memory.get_rework_context_summary()}\n请核验上一轮指出冗余长句是否已被提炼精简。"

                isolated_messages = [
                    {"role": "system", "content": CONTENT_CRITIC_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"请针对以下 PPT 单页文案进行独立严苛的文字与结构盲审：\n\n{text_manifest}{rework_context}"
                    }
                ]
                resp = await llm_client.chat_completion(
                    messages=isolated_messages,
                    role="reasoning",
                    max_tokens=600
                )
                llm_feedback = resp["choices"][0]["message"].get("content", "")
            except Exception as e:
                logger.warning(f"ContentCriticSubagent LLM call error: {e}")

        # 4. Parse results
        strengths = "语言表述结构清晰，符合专业规范。"
        recommendations = list(rule_recs)
        redundancy_issues = list(rule_issues)
        approved = True
        final_score = max(0.0, min(100.0, base_score))

        if llm_feedback:
            m_str = re.search(r'【文案优点[:：]?】\s*(.*?)(?=\n【|\Z)', llm_feedback, re.DOTALL)
            m_tag = re.search(r'【格式与标签诊断[:：]?】\s*(.*?)(?=\n【|\Z)', llm_feedback, re.DOTALL)
            m_risk = re.search(r'【文字冗余诊断[:：]?】\s*(.*?)(?=\n【|\Z)', llm_feedback, re.DOTALL)
            m_rec = re.search(r'【精炼修改建议[:：]?】\s*(.*?)(?=\n【|\Z)', llm_feedback, re.DOTALL)
            m_conc = re.search(r'【内容评审结论[:：]?】\s*(.*?)(?=\n【|\Z)', llm_feedback, re.DOTALL)
            m_score = re.search(r'【内容健康分[:：]?\s*(\d{1,3})\s*(?:/\s*100)?】', llm_feedback)

            if m_str:
                strengths = m_str.group(1).strip()
            if m_tag and "完好闭合" not in m_tag.group(1) and "合规" not in m_tag.group(1):
                redundancy_issues.append(f"标签格式问题: {m_tag.group(1).strip()}")
            if m_risk and "精炼达标" not in m_risk.group(1):
                redundancy_issues.append(m_risk.group(1).strip())
            if m_rec:
                recommendations.append(m_rec.group(1).strip())
            if m_conc:
                approved = "需修正" not in m_conc.group(1)
            if m_score:
                parsed_sc = float(m_score.group(1))
                final_score = round(0.4 * base_score + 0.6 * parsed_sc, 1)
        else:
            approved = final_score >= 70.0

        # Enforce zero-tolerance rule: unclosed tags/format defects strictly reject
        if has_tag_or_format_defect:
            approved = False

        if not recommendations:
            recommendations.append("正文文字精练短小，保持当前精炼标准。")

        verdict_str = "通过" if approved else ("存在未闭合标签或格式缺陷" if has_tag_or_format_defect else "需文字精简修正")
        summary = f"内容与格式结构体检: 得分 {final_score:.1f}/100 [{verdict_str}]。{'; '.join(recommendations[:2])}"

        result = ContentCriticResult(
            approved=approved,
            score=final_score,
            summary=summary,
            strengths=strengths,
            redundancy_issues=redundancy_issues,
            recommendations=recommendations,
            needs_content_refinement=not approved
        )

        # 4.5 Persist round into Subagent dedicated session memory
        if session_memory:
            session_memory.record_audit(
                input_digest=text_manifest[:120],
                approved=approved,
                score=final_score,
                critique_summary=summary,
                defects_or_risks=redundancy_issues,
                recommendations=recommendations
            )

        # 5. Broadcast lifecycle completion: Main agent resumes
        if on_event:
            await cls._safe_emit(on_event, {
                "type": "subagent_lifecycle",
                "phase": "completed",
                "subagent": "ContentCriticSubagent",
                "main_agent_status": "resumed",
                "approved": result.approved,
                "score": result.score,
                "slide_id": slide.id,
                "text": f"内容评审 Subagent 盲审完成 [内容分:{result.score:.1f}, 状态:{'通过' if approved else '需精简'}]，唤醒主 Agent"
            })
            await cls._safe_emit(on_event, {
                "type": "content_critique",
                "status": "completed",
                "slide_id": slide.id,
                "approved": result.approved,
                "score": result.score,
                "summary": result.summary
            })

        return result

    @staticmethod
    async def _safe_emit(on_event: Optional[Callable], data: Dict[str, Any]):
        if not on_event:
            return
        try:
            if inspect.iscoroutinefunction(on_event):
                await on_event(data)
            else:
                res = on_event(data)
                if inspect.isawaitable(res):
                    await res
        except Exception as e:
            logger.debug(f"Content Subagent event emission ignored: {e}")
