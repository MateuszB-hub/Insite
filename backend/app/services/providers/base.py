"""Provider contract for the synthesis layer.

Every backend that can turn a prompt into a Future of Work report implements
`SynthesisProvider`. Providers declare a `tier`:

  local  -- runs on this machine, no API key, no per-token cost (Ollama)
  free   -- no cost to call, but leaves the machine (none today)
  paid   -- metered third-party API; gated behind ENABLE_PAID_PROVIDERS

The registry refuses to hand out a `paid` provider unless paid access has been
explicitly switched on, so a misconfigured env can never silently start
spending money.
"""

from abc import ABC, abstractmethod
from typing import Any, Literal

Tier = Literal["local", "free", "paid"]


class ProviderError(RuntimeError):
    """Raised when a provider cannot fulfill a request."""


class ProviderUnavailable(ProviderError):
    """Provider is not usable right now (daemon down, key missing, etc.)."""


class SynthesisProvider(ABC):
    """A backend capable of producing a structured report from a prompt."""

    #: Stable identifier used in env vars and API responses.
    name: str = "unnamed"

    #: Cost/locality class. See module docstring.
    tier: Tier = "local"

    #: Human-readable label for the UI.
    label: str = "Unnamed provider"

    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Return a JSON object conforming to `schema`.

        Implementations should use native structured-output support where the
        backend offers it, and fall back to prompt instructions plus parsing.
        """

    async def health(self) -> tuple[bool, str | None]:
        """Return (usable, reason_if_not). Cheap, non-generating check."""
        return True, None

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "tier": self.tier, "label": self.label}
