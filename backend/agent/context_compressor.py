"""Context Window Token Accounting and Auto-Compression Engine.

Tracks cumulative and current dialogue/prompt token usage against a configurable
window limit (e.g., 256k, 512k, 1m). When usage reaches >= 90% of the threshold:
1. Automatically condenses older conversation turns and intermediate subagent telemetry.
2. Extracts concise executive summaries of previous design iterations.
3. Emits 'context_usage' telemetry events for real-time frontend visualization.
"""

from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Standard token limit presets
CONTEXT_LIMIT_PRESETS: Dict[str, int] = {
    "128k": 128 * 1024,
    "256k": 256 * 1024,
    "512k": 512 * 1024,
    "1m": 1024 * 1024,
    "2m": 2048 * 1024,
}

AUTO_COMPRESSION_THRESHOLD = 0.90  # 90% trigger


def estimate_tokens(text: str) -> int:
    """Fast, deterministic character/token ratio estimator for mixed Chinese/English.
    
    Rule of thumb:
    - 1 Chinese character ≈ 1.5 ~ 2 tokens (average ~1.8 in typical BPE)
    - 1 English word (4 chars) ≈ 1 token
    - Structured JSON/punctuation ≈ 1 char per token
    """
    if not text:
        return 0
    cjk_count = 0
    ascii_count = 0
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f':
            cjk_count += 1
        else:
            ascii_count += 1
    # Weighted token estimation
    return int(cjk_count * 1.6 + ascii_count * 0.3) + 1


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """Estimates total token footprint for a list of conversation messages."""
    total = 0
    for m in messages:
        # Role overhead
        total += 4
        content = m.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""))
                elif isinstance(part, dict) and part.get("type") == "image_url":
                    # Low-detail snapshot image ~85 tokens, high-detail ~765 tokens
                    total += 170

        # Tool calls overhead
        tool_calls = m.get("tool_calls", [])
        if tool_calls:
            total += estimate_tokens(json.dumps(tool_calls, ensure_ascii=False))

    return total


@dataclass
class ContextUsageReport:
    """Context window utilization report."""
    current_tokens: int
    max_tokens: int
    usage_percent: float
    is_compressed: bool = False
    compression_ratio: float = 1.0
    tokens_saved: int = 0
    context_limit_key: str = "256k"

    @property
    def threshold_reached(self) -> bool:
        return self.usage_percent >= (AUTO_COMPRESSION_THRESHOLD * 100.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_tokens": self.current_tokens,
            "max_tokens": self.max_tokens,
            "usage_percent": round(self.usage_percent, 2),
            "is_compressed": self.is_compressed,
            "compression_ratio": round(self.compression_ratio, 2),
            "tokens_saved": self.tokens_saved,
            "context_limit_key": self.context_limit_key,
            "threshold_reached": self.threshold_reached
        }


class ContextCompressor:
    """Manages dialogue history compression and token budget guardrails."""

    MANUAL_ANCHOR_ID = "compressed_history_anchor"

    @classmethod
    def build_anchor(
        cls,
        messages: List[Dict[str, Any]],
        max_tokens: int = 256 * 1024,
        context_key: str = "256k",
        keep_recent: int = 4,
    ) -> Tuple[Optional[Dict[str, Any]], int, ContextUsageReport]:
        """Force-condense older messages into a reusable, persistable anchor.

        Unlike :meth:`evaluate_and_compress` this ignores the 90% threshold and is
        intended for the user-triggered "compress context" command. It returns the
        synthetic anchor message, the number of raw messages it covers (so the
        caller can later assemble ``[anchor] + messages[covered:]``), and a usage
        report. The raw transcript is never modified by this method.
        """
        initial_tokens = estimate_messages_tokens(messages)
        usage_pct = (initial_tokens / max(max_tokens, 1)) * 100.0

        if len(messages) <= keep_recent:
            report = ContextUsageReport(
                current_tokens=initial_tokens,
                max_tokens=max_tokens,
                usage_percent=usage_pct,
                is_compressed=False,
                context_limit_key=context_key,
            )
            return None, 0, report

        head = messages[:-keep_recent]
        tail = messages[-keep_recent:]

        summary_points: List[str] = []
        for m in head:
            role_label = "用户" if m.get("role") == "user" else "架构师"
            content = str(m.get("content", ""))
            truncated = content[:80] + ("..." if len(content) > 80 else "")
            summary_points.append(f"• [{role_label} 轮次]: {truncated}")

        condensed_text = (
            "【历史上下文手动压缩摘要（用户主动触发）】:\n"
            + "\n".join(summary_points[:20])
            + f"\n（共手动归档压缩 {len(head)} 条历史对话轮次，保留核心设计结论）"
        )
        anchor = {
            "role": "system",
            "content": condensed_text,
            "id": cls.MANUAL_ANCHOR_ID,
        }

        assembled = [anchor] + tail
        compressed_tokens = estimate_messages_tokens(assembled)
        saved = max(0, initial_tokens - compressed_tokens)
        report = ContextUsageReport(
            current_tokens=compressed_tokens,
            max_tokens=max_tokens,
            usage_percent=(compressed_tokens / max(max_tokens, 1)) * 100.0,
            is_compressed=True,
            compression_ratio=compressed_tokens / max(initial_tokens, 1),
            tokens_saved=saved,
            context_limit_key=context_key,
        )
        return anchor, len(messages) - keep_recent, report

    @classmethod
    def assemble_model_messages(
        cls,
        messages: List[Dict[str, Any]],
        anchor: Optional[Dict[str, Any]],
        through_index: int,
    ) -> List[Dict[str, Any]]:
        """Builds the model-facing list from a persisted manual anchor + live tail."""
        if anchor and through_index >= 0 and through_index <= len(messages):
            return [anchor] + messages[through_index:]
        return messages

    @classmethod
    def evaluate_and_compress(
        cls,
        messages: List[Dict[str, Any]],
        max_tokens: int = 256 * 1024,
        context_key: str = "256k",
        force_compress: bool = False
    ) -> Tuple[List[Dict[str, Any]], ContextUsageReport]:
        """Calculates token usage and performs automatic sliding-window semantic compression if >= 90%."""
        initial_tokens = estimate_messages_tokens(messages)
        usage_pct = (initial_tokens / max(max_tokens, 1)) * 100.0

        if not force_compress and usage_pct < (AUTO_COMPRESSION_THRESHOLD * 100.0):
            # Healthy: no compression needed
            report = ContextUsageReport(
                current_tokens=initial_tokens,
                max_tokens=max_tokens,
                usage_percent=usage_pct,
                is_compressed=False,
                context_limit_key=context_key
            )
            return messages, report

        # Trigger 90% Auto-Compression:
        # Keep the initial system instruction (if any) and the most recent 4 messages.
        # Condense the intermediate dialogue into a concise executive memory anchor.
        if len(messages) <= 5:
            # Too few messages to meaningfully compress, return as is
            report = ContextUsageReport(
                current_tokens=initial_tokens,
                max_tokens=max_tokens,
                usage_percent=usage_pct,
                is_compressed=False,
                context_limit_key=context_key
            )
            return messages, report

        system_msg = messages[0] if messages[0].get("role") == "system" else None
        recent_messages = messages[-4:]
        middle_messages = messages[1:-4] if system_msg else messages[:-4]

        # Condense middle messages into a structured summary
        summary_points: List[str] = []
        for idx, m in enumerate(middle_messages):
            role_label = "用户" if m.get("role") == "user" else "架构师"
            content = str(m.get("content", ""))
            truncated = content[:80] + ("..." if len(content) > 80 else "")
            summary_points.append(f"• [{role_label} 轮次]: {truncated}")

        condensed_text = (
            "【历史上下文自动压缩摘要（因达到上下文窗口 90% 阈值已归档）】:\n" +
            "\n".join(summary_points[:8]) +
            f"\n（共自动归档压缩 {len(middle_messages)} 条历史对话轮次，保留核心设计结论）"
        )

        compressed_anchor = {
            "role": "system",
            "content": condensed_text,
            "id": "compressed_history_anchor"
        }

        new_messages: List[Dict[str, Any]] = []
        if system_msg:
            new_messages.append(system_msg)
        new_messages.append(compressed_anchor)
        new_messages.extend(recent_messages)

        compressed_tokens = estimate_messages_tokens(new_messages)
        saved = max(0, initial_tokens - compressed_tokens)
        new_usage_pct = (compressed_tokens / max(max_tokens, 1)) * 100.0
        ratio = compressed_tokens / max(initial_tokens, 1)

        logger.info(
            f"Context Auto-Compression executed: {initial_tokens} -> {compressed_tokens} tokens "
            f"(saved {saved} tokens, new usage: {new_usage_pct:.1f}%)"
        )

        report = ContextUsageReport(
            current_tokens=compressed_tokens,
            max_tokens=max_tokens,
            usage_percent=new_usage_pct,
            is_compressed=True,
            compression_ratio=ratio,
            tokens_saved=saved,
            context_limit_key=context_key
        )

        return new_messages, report
