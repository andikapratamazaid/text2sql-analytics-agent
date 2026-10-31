"""LLM client abstraction.

The agent only needs one method: create(system, messages, tools) -> dict, where the dict looks like
  {"content": [{"type": "text", "text": ...} | {"type": "tool_use", "id", "name", "input"}],
   "stop_reason": str, "usage": {"input_tokens": int, "output_tokens": int}}
Messages use the Anthropic Messages API format, so swapping providers means writing one adapter.
"""
from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    def create(self, system: str, messages: list[dict], tools: list[dict]) -> dict: ...


class AnthropicClient:
    """Adapter for the Anthropic Messages API (reads ANTHROPIC_API_KEY from the environment)."""

    def __init__(self, model: str, max_tokens: int = 1500, api_key: str | None = None):
        try:
            import anthropic
        except ImportError as e:                                  # pragma: no cover
            raise RuntimeError("Install the SDK first: pip install anthropic") from e
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model, self.max_tokens = model, max_tokens

    def create(self, system: str, messages: list[dict], tools: list[dict]) -> dict:   # pragma: no cover
        resp = self._client.messages.create(
            model=self.model, max_tokens=self.max_tokens,
            system=system, tools=tools, messages=messages,
        )
        content = []
        for block in resp.content:
            if block.type == "text":
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": dict(block.input)})
        usage = getattr(resp, "usage", None)
        return {
            "content": content,
            "stop_reason": resp.stop_reason,
            "usage": {"input_tokens": getattr(usage, "input_tokens", 0), "output_tokens": getattr(usage, "output_tokens", 0)},
        }
