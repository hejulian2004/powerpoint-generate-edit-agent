"""Agent Memory and Context Management."""

from __future__ import annotations
from typing import List, Dict, Any


class AgentMemory:
    """Stores user preferences, styling guidelines, and recent activity logs."""

    def __init__(self):
        self.preferences: Dict[str, Any] = {
            "style": "clean modern",
            "density": "balanced",
            "primary_color": "#2563EB",
            "font_family": "Segoe UI",
            "card_radius": 12.0
        }
        self.design_rules: List[str] = [
            "画布基准分辨率为 1280x720，所有元素坐标与尺寸均以此为准。",
            "幻灯片排版讲究呼吸感与留白，重要标题字号建议 32~44px，正文字号建议 16~20px。",
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
