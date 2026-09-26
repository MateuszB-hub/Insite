"""Provider registry and selection policy.

Selection order for SYNTHESIS_PROVIDER=auto (the default):

  1. ollama  -- local, free, private. Preferred whenever the daemon is up.
  2. anthropic -- only if paid access is explicitly enabled.
  3. mock    -- always works, never pretends to be real analysis.

A `paid` provider is never selected by `auto`. Spending money is opt-in: set
ENABLE_PAID_PROVIDERS=true and either name it explicitly via SYNTHESIS_PROVIDER
or pass it per-request.
"""

import logging
import os

from .anthropic_provider import AnthropicProvider
from .base import (
    ProviderError,
    ProviderUnavailable,
    SynthesisProvider,
    Tier,
)
from .mock_provider import MockProvider
from .ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)

__all__ = [
    "SynthesisProvider",
    "ProviderError",
    "ProviderUnavailable",
    "Tier",
    "get_provider",
    "available_providers",
    "paid_enabled",
]

_TRUTHY = {"1", "true", "yes", "on"}

# Registry of constructors, in `auto` preference order.
_REGISTRY: dict[str, type[SynthesisProvider]] = {
    "ollama": OllamaProvider,
    "anthropic": AnthropicProvider,
    "mock": MockProvider,
}

_AUTO_ORDER = ["ollama", "mock"]


def paid_enabled() -> bool:
    """Whether metered providers may be used at all."""
    return os.getenv("ENABLE_PAID_PROVIDERS", "").strip().lower() in _TRUTHY


def _construct(name: str) -> SynthesisProvider:
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise ProviderError(
            f"Unknown provider '{name}'. Known: {', '.join(_REGISTRY)}"
        ) from None


async def get_provider(requested: str | None = None) -> SynthesisProvider:
    """Resolve the provider to use for one request.

    `requested` (from the API call) wins over SYNTHESIS_PROVIDER, which wins
    over `auto`. Paid providers are refused unless paid access is enabled.
    """
    name = (requested or os.getenv("SYNTHESIS_PROVIDER", "auto")).strip().lower()

    if name == "auto":
        return await _auto_select()

    provider = _construct(name)

    if provider.tier == "paid" and not paid_enabled():
        raise ProviderUnavailable(
            f"'{name}' is a paid provider. Set ENABLE_PAID_PROVIDERS=true to "
            "allow metered API calls."
        )

    usable, reason = await provider.health()
    if not usable:
        raise ProviderUnavailable(f"{provider.label} unavailable: {reason}")

    return provider


async def _auto_select() -> SynthesisProvider:
    """Pick the best free/local provider that is actually up."""
    for name in _AUTO_ORDER:
        provider = _construct(name)
        usable, reason = await provider.health()
        if usable:
            logger.info("auto-selected synthesis provider: %s", provider.name)
            return provider
        logger.info("provider %s unavailable: %s", name, reason)

    # MockProvider.health() never fails, so this is unreachable in practice.
    return MockProvider()


async def available_providers() -> list[dict]:
    """Describe every registered provider and whether it is usable now.

    Powers GET /api/providers so the UI can show real options.
    """
    out = []
    for name, cls in _REGISTRY.items():
        provider = cls()
        info = provider.describe()

        if provider.tier == "paid" and not paid_enabled():
            info["available"] = False
            info["reason"] = "Paid providers are disabled"
            info["locked"] = True
        else:
            usable, reason = await provider.health()
            info["available"] = usable
            info["reason"] = reason
            info["locked"] = False

        out.append(info)
    return out
