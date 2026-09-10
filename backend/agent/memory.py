"""Agent Memory and Context Management."""

from __future__ import annotations
from typing import List, Dict, Any


class AgentMemory:
    """Stores user preferences, styling guidelines, and recent activity logs."""

    def __init__(self):
        self.preferences: Dict[str, Any] = {
            "style": "technical editorial",
            "density": "concise",
            "primary_color": "#C2410C",
            "font_family": "Microsoft YaHei",
            "card_radius": 2.0
        }
        self.design_rules: List[str] = [
            "画布基准分辨率为 1280x720，所有元素坐标与尺寸均以此为准。",
            "幻灯片排版讲究呼吸感与留白，重要标题字号建议 32~44px，正文字号建议 16~20px。",
            "文字必须精简：每页标题一句话，正文用短语或要点（每条 ≤ 20 字），绝不堆砌整段文字；放不下的内容拆页或删减。",
            "语言以中文为主：所有标题、正文、卡片文案一律使用中文，专业术语保留中文表达，英文缩写可保留（如 AD、RL、LLM）。",
            "结构与格式严谨性：正文所有 HTML/XML 伪标签（<b>, <i> 等）及标点符号（《》, （）, 【】, “”）必须严格成对对称闭合，严禁格式破坏与语法泄漏。",
            "评审隔离与分权原则：结构评审（纯机械校验标签闭合/格式契约）、内容评审（语义精炼度）、视觉评审（纯排版对齐/留白美观）职责严格隔离，评审 Subagent 纯只读，不通过一律回退链路重做。",
            "禁止在 PPT 中使用大圆角的背景卡片；卡片圆角保持极小（radius 0~3px）或使用直角矩形，并避免给卡片叠加阴影。",
            "可用主题强调色的双色渐变（accent → accent_soft）做装饰色带、标题下划条、数值块等点缀，增强页面层次感；一页只用一个主色系。",
            "多个卡片并列时保持统一宽度与间距（推荐间距 24~32px），避免边缘重叠与溢出画布。",
            "严格使用工具修改 PPT-IR，工具调用后会自动生成版本快照供用户撤销/重做。"
        ]
        self.recent_activities: List[str] = []

    def log_action(self, summary: str):
        self.recent_activities.append(summary)
        if len(self.recent_activities) > 20:
            self.recent_activities.pop(0)

    def update_preference(self, key: str, value: Any):
        self.preferences[key] = value

    def build_system_context(self) -> str:
        rules_text = "\n".join(f"- {r}" for r in self.design_rules)
        prefs_text = ", ".join(f"{k}: {v}" for k, v in self.preferences.items())
        recent_text = "\n".join(f"- {a}" for a in self.recent_activities[-5:]) if self.recent_activities else "（暂无历史）"

        return f"""【设计规范与原则】:
{rules_text}

【用户偏好设置】:
{prefs_text}

【近期修改活动】:
{recent_text}
"""
