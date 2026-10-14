"""Keep the default test run off the network and off Gemini."""

from __future__ import annotations

import pytest


def _raise_llm(*_args, **_kwargs):
    raise RuntimeError("offline test: structured LLM is not called")


@pytest.fixture(autouse=True)
def offline_agents(monkeypatch):
    monkeypatch.setattr("src.graph.stage1_graph.invoke_structured_llm", _raise_llm)
    monkeypatch.setattr("src.graph.stage2_graph.invoke_structured_llm", _raise_llm)
    monkeypatch.setattr(
        "src.graph.stage1_graph.live_web_search",
        lambda *_args, **_kwargs: "offline test search context",
    )
    monkeypatch.setattr(
        "src.graph.stage2_graph.live_web_search",
        lambda *_args, **_kwargs: "offline test search context",
    )
