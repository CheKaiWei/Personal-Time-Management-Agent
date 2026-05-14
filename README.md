# Calendar Agent

[![CI](https://github.com/langchain-ai/new-langgraph-project/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/langchain-ai/new-langgraph-project/actions/workflows/unit-tests.yml)
[![Integration Tests](https://github.com/langchain-ai/new-langgraph-project/actions/workflows/integration-tests.yml/badge.svg)](https://github.com/langchain-ai/new-langgraph-project/actions/workflows/integration-tests.yml)

This project is a minimal [LangGraph](https://github.com/langchain-ai/langgraph) chat agent backed by the OpenAI Responses API. It can be exercised from a terminal with a tiny CLI, or from LangGraph Studio / `langgraph dev`.

<div align="center">
  <img src="./static/studio_ui.png" alt="Graph view in LangGraph studio UI" width="75%" />
</div>

The graph stays intentionally small: one LangGraph node receives chat history, loads OpenAI settings, calls the model, and appends the assistant reply.

## Getting Started

1. Install dependencies, along with the [LangGraph CLI](https://langchain-ai.github.io/langgraph/concepts/langgraph_cli/), which will be used to run the server.

```bash
cd path/to/your/app
pip install -e . "langgraph-cli[inmem]"
```

2. Copy `.env.example` if you want local overrides.

```bash
cp .env.example .env
```

OpenAI configuration priority:

- `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` in `.env` or your shell
- fallback to `~/.codex/auth.json` for `OPENAI_API_KEY`
- fallback to `~/.codex/config.toml` for `base_url` and default model

If you want to enable LangSmith tracing, add `LANGSMITH_API_KEY=...` to `.env`.

3. Start the LangGraph Server.

```shell
langgraph dev
```

4. Or run the minimal terminal chat sample.

```bash
python -m agent.cli "Summarize my day"
```

For an interactive terminal chat:

```bash
calendar-chat
```

## How to customize

1. Adjust defaults in [src/agent/config.py](./src/agent/config.py) if you want a different prompt, model, or timeout.
2. Extend [src/agent/graph.py](./src/agent/graph.py) if you want tools, routing, or memory beyond the current single-node chat flow.

## Development

Run tests with:

```bash
python -m pytest
```
