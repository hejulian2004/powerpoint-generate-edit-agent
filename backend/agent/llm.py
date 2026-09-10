"""OpenAI-compatible LLM Provider with Multi-Model Routing and Streaming Support."""

from __future__ import annotations
import json
import httpx
from typing import List, Dict, Any, Optional, AsyncIterator, Tuple
from ..config import settings


class LLMConfigurationError(RuntimeError):
    """Raised when the agent has no live LLM credentials outside test mode."""


class LLMClient:
    """Async client for OpenAI-compatible completions & tool calling."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None
    ):
        self.base_url = (base_url or settings.openai_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.openai_api_key
        self.default_model = default_model or settings.default_model

    def _is_unconfigured(self) -> bool:
        return not self.api_key or str(self.api_key).startswith("mock_")

    def _mock_allowed(self) -> bool:
        """Silent mock fallback is a test-only affordance, never a production behavior."""
        return settings.app_env in ("test", "dev") and settings.mock_llm

    def _raise_if_unconfigured(self) -> None:
        if not self._mock_allowed():
            raise LLMConfigurationError(
                "LLM API key is not configured. Set OPENAI_API_KEY / configure the model "
                "endpoint before using the agent. Note: mock completions are only permitted "
                "when APP_ENV=test/dev and MOCK_LLM=true."
            )

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def get_model_for_role(self, role: str = "default") -> str:
        if role == "reasoning":
            return settings.reasoning_model or self.default_model
        elif role == "vision":
            return settings.vision_model or self.default_model
        elif role == "fast":
            return settings.fast_model or self.default_model
        return self.default_model

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = "auto",
        role: str = "default",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False
    ) -> Dict[str, Any]:
        """Execute a standard chat completion request."""
        model = self.get_model_for_role(role)
        url = f"{self.base_url}/chat/completions"

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice

        # If API key is empty or dummy, mock only in explicit test mode; fail fast otherwise.
        if self._is_unconfigured():
            if self._mock_allowed():
                return self._mock_completion(messages, tools)
            self._raise_if_unconfigured()

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(url, headers=self._get_headers(), json=payload)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                # Return error or fallback
                raise RuntimeError(f"LLM API request failed: {e}")

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        role: str = "default",
        temperature: float = 0.7
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream chunks from OpenAI-compatible endpoint."""
        model = self.get_model_for_role(role)
        url = f"{self.base_url}/chat/completions"

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        if self._is_unconfigured():
            # Mock stream only in explicit test mode; fail fast otherwise.
            if not self._mock_allowed():
                self._raise_if_unconfigured()
            mock_res = self._mock_completion(messages, tools)
            yield {
                "type": "content",
                "delta": mock_res["choices"][0]["message"].get("content", "")
            }
            if "tool_calls" in mock_res["choices"][0]["message"]:
                yield {
                    "type": "tool_calls",
                    "tool_calls": mock_res["choices"][0]["message"]["tool_calls"]
                }
            return

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, headers=self._get_headers(), json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        if "content" in delta and delta["content"]:
                            yield {"type": "content", "delta": delta["content"]}
                        if "tool_calls" in delta and delta["tool_calls"]:
                            yield {"type": "tool_calls", "delta": delta["tool_calls"]}
                    except Exception:
                        continue

    def _mock_completion(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Provides smart rule-based fallback responses when no live API key is present."""
        last_msg = messages[-1]["content"] if messages else ""
        if isinstance(last_msg, list):
            # Multimodal content
            last_text = " ".join(item.get("text", "") for item in last_msg if item.get("type") == "text")
        else:
            last_text = str(last_msg)

        # Basic intent matching for testing and demonstrations
        tool_calls = []
        if "创建" in last_text or "添加" in last_text or "add" in last_text.lower():
            if "标题" in last_text or "title" in last_text.lower():
                tool_calls.append({
                    "id": "call_mock_1",
                    "type": "function",
                    "function": {
                        "name": "add_text",
                        "arguments": json.dumps({
                            "text": "PPT-Agent-Studio 智能演示平台",
                            "x": 100,
                            "y": 80,
                            "width": 1080,
                            "height": 70,
                            "font_size": 36,
                            "font_color": "#1E293B",
                            "bold": True,
                            "align": "center"
                        })
                    }
                })
            else:
                tool_calls.append({
                    "id": "call_mock_2",
                    "type": "function",
                    "function": {
                        "name": "add_shape",
                        "arguments": json.dumps({
                            "shape_type": "roundRect",
                            "x": 140,
                            "y": 200,
                            "width": 300,
                            "height": 160,
                            "fill_color": "#2563EB",
                            "radius": 12.0,
                            "text": "AI 架构设计\n- 自动化解析\n- 实时渲染",
                            "text_color": "#FFFFFF",
                            "font_size": 18
                        })
                    }
                })

        reply_content = "已为您分析幻灯片内容，并规划并执行了相关的 PPT 修改与元素排版。" if tool_calls else "我已准备就绪，可以通过工具精确修改或创建您的演示文稿。"

        choice: Dict[str, Any] = {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": reply_content
            },
            "finish_reason": "tool_calls" if tool_calls else "stop"
        }
        if tool_calls:
            choice["message"]["tool_calls"] = tool_calls

        return {
            "id": "mock_chat_completion",
            "object": "chat.completion",
            "choices": [choice],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        }
