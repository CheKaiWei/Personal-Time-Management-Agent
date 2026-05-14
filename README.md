# Calendar Agent

`calendar_agent` is a LangGraph-based local planning workflow for the sibling
`../calendar/` directory. It is not a generic chat bot. It reads planning
files, uses an LLM to reason about the next action, can ask follow-up
questions in multiple turns, and only writes files after showing a draft.

## Workflows

The CLI exposes four top-level planning workflows:

1. `Weekly Plan`
2. `Temp Plan`
3. `Daily Plan`
4. `Reflect`

`Reflect` is a submenu with three operations:

1. `Daily Reflect`
2. `Weekly Reflect`
3. `Long-term Reflect`

Interactive mode still shows the `1-4` menu, but it also accepts
natural-language commands such as:

- `weekly plan`
- `daily reflect`
- `weekly reflect`
- `long-term reflect`
- `open weekly plan`
- `open daily plan`
- `open long term`

## What Is LLM-Driven

The following steps are decided by the LLM, not by fixed keyword rules:

- `weekly_plan`: choose this week's `5-7` checkpoints
- `temp_plan`: structure temporary tasks
- `daily_plan`: turn weekly checkpoints into `2-4` daily focus items and split
  each into `1-3` MEUs
- `daily_reflect`: ask the user about today's real completion state, provide
  candidate answers, and then generate the final daily summary
- `weekly_reflect`: analyze this week's executed work so far and decide whether
  later days in the same week need schedule adjustments
- `long_term_reflect`: revise only long-term `E` levels and notes based on the
  weekly plan plus current date pressure

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

Note: the project keeps the existing `calendar/{week_start} Weekly Plan.md`
convention. For the week of `2026-05-11`, weekly reflect logs are written back
to `calendar/2026-05-11 Weekly Plan.md`, not to a separate
`2026-05-weekly_planner.md` file.

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

The planning decisions require an OpenAI-compatible model.

Configuration priority:

1. `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`, `OPENAI_SYSTEM_PROMPT`
2. `~/.codex/auth.json`
3. `~/.codex/config.toml`

If no API key is available, the LLM planning workflows fail instead of silently
falling back to rule-only behavior.

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

## Scripted Usage

Run a specific workflow:

```bash
uv run python -m agent.cli --intent weekly_plan --date 2026-05-14 --calendar-dir ..\calendar
uv run python -m agent.cli --intent weekly_reflect --date 2026-05-14 --calendar-dir ..\calendar
uv run python -m agent.cli --intent long_term_reflect --date 2026-05-14 --calendar-dir ..\calendar
```

Run a natural-language command directly:

```bash
uv run python -m agent.cli "open weekly plan" --date 2026-05-14 --calendar-dir ..\calendar
uv run python -m agent.cli "daily reflect" --date 2026-05-14 --calendar-dir ..\calendar
uv run python -m agent.cli "weekly reflect" --date 2026-05-14 --calendar-dir ..\calendar
uv run python -m agent.cli "long-term reflect" --date 2026-05-14 --calendar-dir ..\calendar
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

`Calendar` can now include multiple checkpoint blocks when appropriate, and
`Tasks` groups MEUs under each focus item so daily work is a decomposition of
weekly checkpoints instead of a single checkpoint only.

### Daily Reflect

Only rewrites:

- `Reflect`

The first daily-reflect turn now asks the user about the real completion state
and shows candidate answers before synthesizing the final summary.

### Weekly Reflect

Writes:

- future-day `Calendar` adjustments for the same week only
- appended lines in the weekly file's `# Adjustment Log`

It does not rewrite past dates.

### Long-term Reflect

Writes only:

- long-term `E` level
- long-term `Notes`

It does not modify task names, descriptions, status, priority, DDL, or hours.

## Code Layout

- `src/agent/calendar_files.py`
  - path resolution
  - markdown section parsing
  - Univer long-term table parsing
  - long-term workbook extraction/rendering
- `src/agent/planner.py`
  - LLM prompts
  - multi-turn planning decisions
  - draft normalization
- `src/agent/graph.py`
  - LangGraph workflow
  - interrupt/resume loop
- `src/agent/calendar_writes.py`
  - file patch generation
  - weekly reflect / long-term reflect write boundaries
- `src/agent/cli.py`
  - menu + submenu + natural-language CLI
  - multi-turn user interaction

## Testing

Run all tests:

```bash
uv run python -m pytest
```

Run lint:

```bash
uv run python -m ruff check .
```

The test suite mocks the LLM planning turns, verifies interrupt/resume behavior,
and keeps file writes deterministic.
