import importlib

import pytest

from agent import graph
from agent.config import DEFAULT_SYSTEM_PROMPT, OpenAISettings

graph_module = importlib.import_module("agent.graph")

pytestmark = pytest.mark.anyio


async def test_agent_returns_assistant_message(monkeypatch) -> None:
    async def fake_generate_assistant_message(messages, settings, client=None) -> str:
        assert messages == [{"role": "user", "content": "hello"}]
        assert settings == OpenAISettings(
            api_key="test-key",
            model="gpt-5.4",
            base_url=None,
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            timeout=30.0,
        )
        return "stub reply"

    monkeypatch.setattr(
        graph_module,
        "generate_assistant_message",
        fake_generate_assistant_message,
    )
    monkeypatch.setattr(
        graph_module,
        "resolve_openai_settings",
        lambda model=None, system_prompt=None: OpenAISettings(api_key="test-key"),
    )

    result = await graph.ainvoke({"messages": [{"role": "user", "content": "hello"}]})

    assert result["response"] == "stub reply"
    assert result["messages"][-1] == {"role": "assistant", "content": "stub reply"}
