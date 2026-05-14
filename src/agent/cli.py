"""Minimal terminal chat entrypoint for the calendar agent."""

from __future__ import annotations

import argparse
import asyncio
import sys

from agent.graph import ChatMessage, graph


def build_parser() -> argparse.ArgumentParser:
    """Create a CLI parser for one-shot and interactive chat usage."""
    parser = argparse.ArgumentParser(description="Chat with the calendar agent.")
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Optional one-shot prompt. If omitted, an interactive terminal chat starts.",
    )
    return parser


async def _run(prompt: str | None) -> None:
    """Run a single request or an interactive terminal loop."""
    if prompt:
        result = await graph.ainvoke({"messages": [{"role": "user", "content": prompt}]})
        sys.stdout.write(f"{result['response']}\n")
        return

    history: list[ChatMessage] = []
    sys.stdout.write("Type `exit` to quit.\n")

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            return
        if not user_input:
            continue

        history.append({"role": "user", "content": user_input})
        result = await graph.ainvoke({"messages": history})
        history = result["messages"]
        sys.stdout.write(f"Assistant: {result['response']}\n")


def main() -> None:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()
    prompt = " ".join(args.prompt).strip() or None
    asyncio.run(_run(prompt))


if __name__ == "__main__":
    main()
