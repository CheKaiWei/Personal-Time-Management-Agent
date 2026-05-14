# Calendar Agent

`calendar_agent` is a LangGraph-based local planning workflow for the sibling
`../calendar/` directory. It is not a generic chat bot. It reads planning files,
uses an LLM to reason about the next action, can ask follow-up questions in
multiple turns, and only writes files after showing a draft.

## Workflows

The CLI exposes four workflows:

1. `Weekly Plan`
2. `Temp Plan`
3. `Daily Plan`
4. `Daily Reflect`

The menu is:

```text
calendar-chat

1. Weekly Plan
2. Temp Plan
3. Daily Plan
4. Daily Reflect
请选择:
```

## What Is LLM-Driven

The following steps are now decided by the LLM, not by fixed keyword rules:

- `weekly_plan`: choose this week's `3-5` checkpoints
- `temp_plan`: structure temporary tasks
- `daily_plan`: choose today's single checkpoint and split it into `1-3` MEUs
- `daily_reflect`: ask reflection questions and produce the final summary

Each workflow can pause and ask the user a clarification question. The CLI then
resumes the same LangGraph thread and continues planning. This allows multi-turn
Q&A before the final draft is produced.

## File Contract

The project reads and writes these files in `../calendar/`:

- `calendar/{YYYY-MM} Long-term.univer.md`
- `calendar/{week_start} Weekly Plan.md`
- `calendar/{date}.md`

Week start is Monday. For example, `2026-05-14` maps to:

- weekly file: `calendar/2026-05-11 Weekly Plan.md`
- daily file: `calendar/2026-05-14.md`

## Install

From `calendar_agent/`:

```bash
uv sync
```

Or:

```bash
pip install -e .
```

## OpenAI Requirement

The planning decisions now require an OpenAI-compatible model.

Configuration priority:

1. `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`, `OPENAI_SYSTEM_PROMPT`
2. `~/.codex/auth.json`
3. `~/.codex/config.toml`

If no API key is available, the LLM planning workflows will fail instead of
silently falling back to rule-only behavior.

## Running The CLI

Recommended:

```bash
uv run python -m agent.cli
```

If you want to use `calendar-chat` directly in `Git Bash`, first activate the
virtual environment:

```bash
source .venv/Scripts/activate
calendar-chat
```

Or call the generated executable directly:

```bash
./.venv/Scripts/calendar-chat.exe
```

Note: on this Windows setup, `uv run calendar-chat` may hit a `uv trampoline`
permission issue. Prefer `uv run python -m agent.cli`.

## Non-Menu Usage

You can skip the menu and call a specific workflow:

```bash
uv run python -m agent.cli --intent weekly_plan --date 2026-05-14 --calendar-dir ..\calendar
```

Write changes immediately:

```bash
uv run python -m agent.cli --intent weekly_plan --date 2026-05-14 --calendar-dir ..\calendar --apply
uv run python -m agent.cli --intent temp_plan --date 2026-05-14 --calendar-dir ..\calendar --apply
uv run python -m agent.cli --intent daily_plan --date 2026-05-14 --calendar-dir ..\calendar --apply
uv run python -m agent.cli --intent daily_reflect --date 2026-05-14 --calendar-dir ..\calendar --apply
```

`--apply` skips the final write confirmation. It does not skip LLM follow-up
questions. If the LLM needs clarification, the CLI still asks the user.

## Multi-Turn Q&A Flow

Each workflow follows this pattern:

1. Read the relevant `calendar/` files.
2. Ask the LLM for a planning decision.
3. If the LLM needs more context, pause and ask one question.
4. Resume the same LangGraph thread with the user's answer.
5. Repeat until the LLM returns a final draft.
6. Show the draft and planned file updates.
7. Optionally write the files.

Type `exit`, `quit`, or `cancel` at a follow-up question to stop the workflow.

## What Gets Written

### Weekly Plan

Maintains:

- `# Weekly Checkpoint`
- `# Temp Tasks`
- `# Daily Links`
- `# Adjustment Log`

Also creates missing daily templates for the week.

### Temp Plan

Rewrites the `# Temp Tasks` section using structured output from the LLM.

### Daily Plan

Maintains:

- `# Calendar`
- `# Tasks`
- `# Notes`
- `# Reflect`

Only rewrites:

- `Calendar`
- `Tasks`

### Daily Reflect

Only rewrites:

- `Reflect`

## Code Layout

- `src/agent/calendar_files.py`
  - path resolution
  - markdown section parsing
  - Univer long-term table parsing
- `src/agent/planner.py`
  - LLM prompts
  - multi-turn planning decisions
  - draft normalization
- `src/agent/graph.py`
  - LangGraph workflow
  - interrupt/resume loop
- `src/agent/calendar_writes.py`
  - file patch generation
  - writing files
- `src/agent/cli.py`
  - menu CLI
  - multi-turn user interaction

## Testing

Run all tests:

```bash
uv run python -m pytest
```

Run lint:

```bash
uv run ruff check .
```

The test suite mocks the LLM planning turns, verifies interrupt/resume behavior,
and keeps file writes deterministic.

## Minimal Real Check

One real dry-run used during development:

```bash
uv run python -m agent.cli --intent temp_plan --date 2026-05-14 --calendar-dir ..\calendar
```

This confirmed that the graph now performs an actual OpenAI call instead of
always staying inside deterministic local rules.
