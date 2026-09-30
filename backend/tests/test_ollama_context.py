"""The local model is given room for the whole prompt, and a cut-off answer
is reported as such.

Live, Ollama's default context (2-4k tokens) cut a 7-page résumé to 2,050 of
its ~4,300 tokens without a word; the model then ran to the 300 s timeout,
and the site showed Cloudflare's 524 page.
"""

import asyncio
import json

import httpx
import pytest

from app.services.providers import ollama_provider as op
from app.services.providers.base import ProviderUnavailable


def test_short_prompts_get_the_minimum_context():
    assert op.context_size("x" * 300) == op.MIN_CONTEXT


def test_a_long_prompt_fits_whole_with_room_for_the_answer():
    prompt = "x" * 21_000          # the 7-page résumé's prompt
    ctx = op.context_size(prompt)
    assert ctx >= 21_000 // 3 + op.MAX_OUTPUT_TOKENS
    assert ctx % 1024 == 0


def test_context_is_capped():
    assert op.context_size("x" * 500_000) == op.MAX_CONTEXT


def _provider_answering(monkeypatch, payload, seen):
    """An OllamaProvider whose HTTP calls are answered locally."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            seen.update(json.loads(request.content))
            return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(op.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    provider = op.OllamaProvider(model="llama3.1")

    async def healthy():
        return True, None
    monkeypatch.setattr(provider, "health", healthy)
    return provider


def test_every_request_sizes_the_context_and_caps_the_answer(monkeypatch):
    seen: dict = {}
    provider = _provider_answering(
        monkeypatch, {"message": {"content": '{"ok": true}'}, "done_reason": "stop"}, seen)
    prompt = "résumé text " * 1500
    assert asyncio.run(provider.generate_json(prompt, {"type": "object"})) == {"ok": True}
    assert seen["options"]["num_ctx"] == op.context_size(prompt)
    assert seen["options"]["num_predict"] == op.MAX_OUTPUT_TOKENS


def test_an_answer_cut_off_at_the_cap_is_reported_not_parsed(monkeypatch):
    provider = _provider_answering(
        monkeypatch, {"message": {"content": '{"jobs": [{"title": "Nur'}, "done_reason": "length"}, {})
    with pytest.raises(ProviderUnavailable, match="length limit"):
        asyncio.run(provider.generate_json("prompt", {"type": "object"}))


# --- the host is a fanless laptop: one run at a time, unload soon, log cost ---

def test_each_request_unloads_the_model_soon(monkeypatch):
    seen: dict = {}
    provider = _provider_answering(
        monkeypatch, {"message": {"content": '{"ok": true}'}, "done_reason": "stop"}, seen)
    asyncio.run(provider.generate_json("prompt", {"type": "object"}))
    assert seen["keep_alive"] == op.KEEP_ALIVE == "1m"


def test_two_runs_at_once_take_turns(monkeypatch):
    provider = _provider_answering(
        monkeypatch, {"message": {"content": '{"ok": true}'}, "done_reason": "stop"}, {})
    running, most = 0, 0
    real_post = op.httpx.AsyncClient

    class Slow:
        def __init__(self, **kw):
            self.inner = real_post(**kw)

        async def __aenter__(self):
            await self.inner.__aenter__()
            return self

        async def __aexit__(self, *exc):
            return await self.inner.__aexit__(*exc)

        async def post(self, *a, **kw):
            nonlocal running, most
            running += 1
            most = max(most, running)
            await asyncio.sleep(0.05)
            running -= 1
            return await self.inner.post(*a, **kw)

    monkeypatch.setattr(op.httpx, "AsyncClient", Slow)

    async def both():
        await asyncio.gather(provider.generate_json("a", {}), provider.generate_json("b", {}))
    asyncio.run(both())
    assert most == 1


def test_each_run_is_logged_by_purpose_without_content(monkeypatch, caplog):
    provider = _provider_answering(
        monkeypatch, {"message": {"content": '{"ok": true}'}, "done_reason": "stop",
                      "prompt_eval_count": 12, "eval_count": 3}, {})
    with caplog.at_level("INFO", logger=op.__name__):
        asyncio.run(provider.generate_json("SECRET RÉSUMÉ TEXT", {}, purpose="resume"))
    line = next(r.getMessage() for r in caplog.records if "model run" in r.getMessage())
    assert "purpose=resume" in line and "prompt_tokens=12" in line and "out_tokens=3" in line
    assert "SECRET" not in line
