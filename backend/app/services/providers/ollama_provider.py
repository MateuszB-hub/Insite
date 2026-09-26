"""Local model synthesis via Ollama.

This is the default provider: models run on this machine, so there is no API
key, no per-token cost, and no applicant data leaving the host -- which matters
for an HR portal.

Talks to the Ollama REST API directly over httpx rather than adding the
`ollama` SDK; the two endpoints used here are stable and it keeps the
dependency surface small.
"""

import json
import logging
import os
from typing import Any

import httpx

from .base import ProviderUnavailable, SynthesisProvider

logger = logging.getLogger(__name__)

DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
# Local generation on consumer hardware is slow; this is generous on purpose.
DEFAULT_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "300"))


class OllamaProvider(SynthesisProvider):
    name = "ollama"
    tier = "local"
    label = "Local model (Ollama)"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.label = f"Local model ({model})"
        # Ollama requires the exact tag ("llama3.1:8b"); a bare name 404s.
        # Resolved lazily against /api/tags and cached here.
        self._resolved_model: str | None = None

    async def list_models(self) -> list[str]:
        """Names of every model pulled on this machine."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.host}/api/tags")
            response.raise_for_status()
            payload = response.json()
        return [m.get("name", "") for m in payload.get("models", [])]

    def _match(self, models: list[str]) -> str | None:
        """Resolve a configured name to a concrete tag that Ollama accepts.

        Exact match wins; otherwise fall back to the first tag whose
        repository half matches, so OLLAMA_MODEL=llama3.1 finds llama3.1:8b.
        """
        if self.model in models:
            return self.model
        for name in models:
            if name.split(":")[0] == self.model:
                return name
        return None

    async def health(self) -> tuple[bool, str | None]:
        try:
            models = await self.list_models()
        except Exception as exc:
            return False, (
                f"Ollama not reachable at {self.host} ({exc.__class__.__name__}). "
                "Start it with `ollama serve`."
            )

        resolved = self._match(models)
        if resolved is None:
            return False, (
                f"Model '{self.model}' is not pulled. Available: "
                f"{', '.join(models) or 'none'}. Pull it with "
                f"`ollama pull {self.model}`."
            )

        self._resolved_model = resolved
        if resolved != self.model:
            self.label = f"Local model ({resolved})"
        return True, None

    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        usable, reason = await self.health()
        if not usable:
            raise ProviderUnavailable(reason or "Ollama unavailable")

        request = {
            "model": self._resolved_model or self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            # Ollama supports a JSON schema here, which constrains decoding and
            # is far more reliable than asking the model to behave.
            "format": schema,
            "options": {
                # Low temperature: this is an extraction/summarization task.
                "temperature": 0.3,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.host}/api/chat", json=request)
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                f"Local model timed out after {self.timeout:.0f}s. Try a smaller "
                f"model via OLLAMA_MODEL, or raise OLLAMA_TIMEOUT."
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"Ollama request failed: {exc}") from exc

        content = (payload.get("message") or {}).get("content", "")
        if not content:
            raise ProviderUnavailable("Ollama returned an empty response")

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("ollama returned non-JSON content: %.200s", content)
            raise ProviderUnavailable(
                "Local model did not return valid JSON"
            ) from exc
