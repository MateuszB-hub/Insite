"""Deterministic offline provider.

No model, no network, no keys. Used as the safety net when nothing else is
configured, and in tests where a fixed response is wanted.
"""

from typing import Any

from .base import SynthesisProvider


class MockProvider(SynthesisProvider):
    name = "mock"
    tier = "local"
    label = "Mock (no model)"

    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        # The prompt carries the industry; echo enough to prove the wiring
        # without pretending to have done research.
        return {
            "executive_summary": (
                "Placeholder summary generated without a model. Configure a "
                "local model (Ollama) or enable a paid provider for real "
                "analysis."
            ),
            "trends": [
                {
                    "title": "AI & Automation Integration",
                    "summary": (
                        "Automation is reshaping task composition across roles, "
                        "creating new positions while changing existing ones."
                    ),
                    "source": "Placeholder",
                    "source_url": None,
                },
                {
                    "title": "Remote & Hybrid Work Evolution",
                    "summary": (
                        "Hybrid models continue to consolidate, pushing "
                        "digital-first collaboration norms."
                    ),
                    "source": "Placeholder",
                    "source_url": None,
                },
                {
                    "title": "Skills-Based Hiring",
                    "summary": (
                        "Hiring is shifting from credentials toward "
                        "demonstrable skills, widening the candidate pool."
                    ),
                    "source": "Placeholder",
                    "source_url": None,
                },
            ],
            "skills_in_demand": [
                "Artificial Intelligence & Machine Learning",
                "Data Analysis & Visualization",
                "Cross-functional Collaboration",
                "Adaptive Leadership",
                "Digital Literacy",
            ],
            "outlook": (
                "Placeholder outlook. Enable a real provider to get an "
                "industry-specific career outlook."
            ),
        }
