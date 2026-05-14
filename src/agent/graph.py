"""LangGraph chat node backed by OpenAI responses."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from langgraph.graph import START, StateGraph
from langgraph.runtime import Runtime
from openai import AsyncOpenAI
from typing_extensions import TypedDict

if __package__ in {None, ""}:
    src_root = Path(__file__).resolve().parents[1]
    src_root_str = str(src_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)

from agent.config import OpenAISettings, build_openai_client, resolve_openai_settings


class Context(TypedDict, total=False):
    """Optional runtime overrides for the OpenAI chat call."""

    model: str
    system_prompt: str


class ChatMessage(TypedDict):
    """Minimal chat message payload used by the graph and CLI."""

    role: Literal["user", "assistant"]
    content: str


class State(TypedDict, total=False):
    """Input and output state for the chat graph."""

    messages: list[ChatMessage]
    changeme: str
    response: str


async def call_model(state: State, runtime: Runtime[Context]) -> dict[str, object]:
    """Send the conversation to OpenAI and append the assistant response."""
    messages = _normalize_messages(state)
    runtime_context = runtime.context or {}
    settings = resolve_openai_settings(
        model=runtime_context.get("model"),
        system_prompt=runtime_context.get("system_prompt"),
    )
    assistant_reply = await generate_assistant_message(messages, settings)

    return {
        "messages": [
            *messages,
            {"role": "assistant", "content": assistant_reply},
        ],
        "response": assistant_reply,
        "changeme": assistant_reply,
    }


async def generate_assistant_message(
    messages: list[ChatMessage],
    settings: OpenAISettings,
    client: AsyncOpenAI | None = None,
) -> str:
    """Call the OpenAI Responses API with the provided chat history."""
    if client is None:
        async with build_openai_client(settings) as local_client:
            return await _request_openai_response(local_client, messages, settings)

    return await _request_openai_response(client, messages, settings)


async def _request_openai_response(
    client: AsyncOpenAI,
    messages: list[ChatMessage],
    settings: OpenAISettings,
) -> str:
    """Issue the OpenAI request and extract plain text output."""
    response = await client.responses.create(
        model=settings.model,
        instructions=settings.system_prompt,
        input=[
            {"role": message["role"], "content": message["content"]}
            for message in messages
        ],
    )
    output_text = (response.output_text or "").strip()
    if not output_text:
        raise RuntimeError("OpenAI returned an empty response.")
    return output_text


def _normalize_messages(state: State) -> list[ChatMessage]:
    """Accept either the new `messages` payload or the legacy `changeme` field."""
    messages = state.get("messages")
    if messages:
        return messages

    legacy_prompt = state.get("changeme")
    if legacy_prompt:
        return [{"role": "user", "content": legacy_prompt}]

    raise ValueError("State must include `messages` or `changeme`.")


graph = (
    StateGraph(State, context_schema=Context)
    .add_node("call_model", call_model)
    .add_edge(START, "call_model")
    .compile(name="Calendar Chat Graph")
)
