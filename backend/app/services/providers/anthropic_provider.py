"""Anthropic synthesis -- the metered, paid tier.

Gated: the registry will not construct this unless ENABLE_PAID_PROVIDERS is
truthy AND ANTHROPIC_API_KEY is present. Local providers stay the default.

Structured output is obtained with a single-tool definition whose input schema
is the report schema, and tool_choice forcing that tool. That is the documented
way to get schema-conforming JSON out of the Messages API without parsing prose.
"""

import logging
import os
from typing import Any

from .base import ProviderError, ProviderUnavailable, SynthesisProvider

logger = logging.getLogger(__name__)

# Opus 5 is the most capable; Sonnet 5 is the cost/latency middle ground and a
# better default for a summarization task like this one.
DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
DEFAULT_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))

_TOOL_NAME = "emit_report"


class AnthropicProvider(SynthesisProvider):
    name = "anthropic"
    tier = "paid"
    label = "Anthropic (paid)"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.label = f"Anthropic {model} (paid)"

    async def health(self) -> tuple[bool, str | None]:
        if not os.getenv("ANTHROPIC_API_KEY"):
            return False, "ANTHROPIC_API_KEY is not set"
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "anthropic SDK not installed"
        return True, None

    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        usable, reason = await self.health()
        if not usable:
            raise ProviderUnavailable(reason or "Anthropic unavailable")

        from anthropic import AsyncAnthropic

        client = AsyncAnthropic()  # reads ANTHROPIC_API_KEY

        try:
            message = await client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                tools=[
                    {
                        "name": _TOOL_NAME,
                        "description": "Emit the Future of Work report.",
                        "input_schema": schema,
                    }
                ],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise ProviderUnavailable(f"Anthropic request failed: {exc}") from exc

        for block in message.content:
            if getattr(block, "type", None) == "tool_use":
                return dict(block.input)

        raise ProviderError("Anthropic response contained no tool_use block")
