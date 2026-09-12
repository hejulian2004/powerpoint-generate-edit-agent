"""MemoryService: owns a session's conversation transcript and agent memories.

Everything mutable that the Agent may read across turns lives here, scoped to
exactly one session (S3/S9): the raw conversation transcript, the main
``AgentMemory`` (preferences / design rules / recent activity), and the private
per-subagent memories. ``AgentRuntime`` is stateless and must read/write these
through the session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _default_agent_memory():
    """Lazily constructs an AgentMemory to avoid an import cycle with backend.agent."""
    from ...agent.memory import AgentMemory
    return AgentMemory()


class MemoryService:
    """Owns a session's messages, AgentMemory, and subagent memories."""

    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []
        self.agent_memory: Any = _default_agent_memory()
        # subagent_name -> SubagentSessionMemory; lazily created on demand.
        self.subagent_memories: Dict[str, Any] = {}
        # Manual (user-triggered) compression state. The anchor is a synthetic
        # system message that stands in for the first ``compression_through_index``
        # raw transcript messages; the raw transcript itself is never rewritten.
        self.compressed_anchor: Optional[Dict[str, Any]] = None
        self.compression_through_index: int = 0
        self.compression_report: Optional[Dict[str, Any]] = None

    def clear_conversation(self) -> None:
        """Starts a fresh conversation while leaving document/deck state untouched."""
        self.messages.clear()
        self.agent_memory = _default_agent_memory()
        self.subagent_memories.clear()
        self.compressed_anchor = None
        self.compression_through_index = 0
        self.compression_report = None

    def add_message(
        self,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        vision_critique: Optional[str] = None,
        visual_review: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        msg = {
            "id": f"msg_{uuid.uuid4().hex[:8]}",
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "tool_calls": tool_calls or [],
            "vision_critique": vision_critique,
            "visual_review": visual_review,
        }
        self.messages.append(msg)
        return msg

    def get_subagent_memory(self, subagent_name: str) -> Any:
        """Returns (creating on first use) the private memory for a subagent."""
        mem = self.subagent_memories.get(subagent_name)
        if mem is None:
            from ...agent.subagents.memory import SubagentSessionMemory
            mem = SubagentSessionMemory(subagent_name)
            self.subagent_memories[subagent_name] = mem
        return mem

    def set_subagent_memory(self, subagent_name: str, memory: Any) -> None:
        self.subagent_memories[subagent_name] = memory
