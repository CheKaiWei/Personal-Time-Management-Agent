import importlib

import pytest

from agent.cli import (
    ensure_backend_ready,
    parse_user_command,
    prompt_for_date,
    run_interactive_session,
    run_text_command,
    run_workflow,
)

graph_module = importlib.import_module("agent.graph")

pytestmark = pytest.mark.anyio


def _write_calendar_fixture(tmp_path) -> None:
    (tmp_path / "2026-05 Long-term.univer.md").write_text(
        """
```sheet
{"sheetOrder":["sheet-1"],"sheets":{"sheet-1":{"cellData":{"2":{"0":{"v":"Projects"},"1":{"v":"Tasks"}},"3":{"0":{"v":"Research"},"1":{"v":"Camera ready"},"4":{"v":"P1"},"5":{"v":"E2"},"7":{"v":"6h"}}}}}}
```
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "2026-05-11 Weekly Plan.md").write_text(
        """
# Weekly Checkpoint
- [ ] Existing checkpoint

# Temp Tasks
- [ ] Renew visa

# Daily Links
[[2026-05-14]]
[[2026-05-15]]

# Adjustment Log
- 2026-05-14: initial plan
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "2026-05-14.md").write_text(
        """
# Calendar

# Tasks

# Notes

# Reflect
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "2026-05-15.md").write_text(
        """
# Calendar
- [ ] Old block [startTime:: 09:00] [endTime:: 10:00]

# Tasks
- [ ] Keep this task

# Notes
- Future note

# Reflect
""".strip(),
        encoding="utf-8",
    )


def test_parse_user_command_supports_reflect_submenu() -> None:
    command = parse_user_command("reflect")

    assert command is not None
    assert command.kind == "reflect_menu"


def test_parse_user_command_supports_specific_weekly_reflect() -> None:
    command = parse_user_command("weekly reflect")

    assert command is not None
    assert command.kind == "workflow"
    assert command.intent == "weekly_reflect"


def test_parse_user_command_supports_open_weekly_plan() -> None:
    command = parse_user_command("打开 weekly plan")

    assert command is not None
    assert command.kind == "open_document"
    assert command.document == "weekly_plan"


def test_prompt_for_date_defaults_to_today(monkeypatch) -> None:
    monkeypatch.setattr("agent.cli.get_default_current_date", lambda: "2099-01-02")
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    assert prompt_for_date() == "2099-01-02"


def test_ensure_backend_ready_rejects_missing_calendar_dir(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="Calendar directory does not exist"):
        ensure_backend_ready(tmp_path / "missing")


async def test_run_workflow_daily_reflect_preview_does_not_write_files(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_daily_reflect_turn(**kwargs):
        return {
            "status": "ready",
            "message": "Reflection draft is ready.",
            "draft": {
                "intent": "daily_reflect",
                "current_date": "2026-05-14",
                "reflect_lines": ["- Today was stable."],
            },
        }

    monkeypatch.setattr(graph_module, "plan_daily_reflect_turn", fake_plan_daily_reflect_turn)

    await run_workflow(
        intent="daily_reflect",
        current_date="2026-05-14",
        calendar_dir=tmp_path,
        apply=False,
        prompt_on_write=False,
    )

    daily_text = (tmp_path / "2026-05-14.md").read_text(encoding="utf-8")
    assert "Today was stable." not in daily_text


async def test_run_workflow_weekly_reflect_apply_writes_future_schedule(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_weekly_reflect_turn(**kwargs):
        return {
            "status": "ready",
            "message": "Weekly adjustment is ready.",
            "draft": {
                "intent": "weekly_reflect",
                "current_date": "2026-05-14",
                "adjustment_log_lines": ["- 2026-05-14: moved interview prep to tomorrow afternoon."],
                "future_daily_adjustments": [
                    {
                        "date": "2026-05-15",
                        "reason": "Recovered time today.",
                        "calendar_blocks": [
                            "- [ ] Career / Interview prep [startTime:: 14:00] [endTime:: 15:00]"
                        ],
                    }
                ],
            },
        }

    monkeypatch.setattr(graph_module, "plan_weekly_reflect_turn", fake_plan_weekly_reflect_turn)

    await run_workflow(
        intent="weekly_reflect",
        current_date="2026-05-14",
        calendar_dir=tmp_path,
        apply=True,
        prompt_on_write=False,
    )

    weekly_text = (tmp_path / "2026-05-11 Weekly Plan.md").read_text(encoding="utf-8")
    future_daily_text = (tmp_path / "2026-05-15.md").read_text(encoding="utf-8")
    assert "moved interview prep to tomorrow afternoon" in weekly_text
    assert "Career / Interview prep [startTime:: 14:00]" in future_daily_text


async def test_run_workflow_long_term_reflect_apply_writes_only_long_term(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_long_term_reflect_turn(**kwargs):
        return {
            "status": "ready",
            "message": "Long-term urgency update is ready.",
            "draft": {
                "intent": "long_term_reflect",
                "current_date": "2026-05-14",
                "revisions": [
                    {
                        "row_id": "3",
                        "task": "Research / Camera ready",
                        "current_e_level": "E2",
                        "new_e_level": "E1",
                        "note_append": "Camera ready entered final risk window.",
                        "reason": "Deadline is close.",
                    }
                ],
            },
        }

    monkeypatch.setattr(graph_module, "plan_long_term_reflect_turn", fake_plan_long_term_reflect_turn)

    await run_workflow(
        intent="long_term_reflect",
        current_date="2026-05-14",
        calendar_dir=tmp_path,
        apply=True,
        prompt_on_write=False,
    )

    long_term_text = (tmp_path / "2026-05 Long-term.univer.md").read_text(encoding="utf-8")
    assert '"E1"' in long_term_text
    assert "Camera ready entered final risk window." in long_term_text


async def test_run_workflow_handles_daily_reflect_suggested_answers(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)
    answers = iter(["2"])

    async def fake_plan_daily_reflect_turn(**kwargs):
        qa_history = kwargs["qa_history"]
        if not qa_history:
            return {
                "status": "needs_input",
                "message": "Please confirm today's actual completion.",
                "question": "Which answer fits best?",
                "suggested_answers": ["Completed as planned.", "Partially completed.", "Mostly interrupted."],
            }
        return {
            "status": "ready",
            "message": "Reflection is ready.",
            "draft": {
                "intent": "daily_reflect",
                "current_date": "2026-05-14",
                "reflect_lines": [f"- {qa_history[0]['answer']}"],
            },
        }

    monkeypatch.setattr(graph_module, "plan_daily_reflect_turn", fake_plan_daily_reflect_turn)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr("agent.cli.build_thread_id", lambda **kwargs: "test-daily-reflect")

    result = await run_workflow(
        intent="daily_reflect",
        current_date="2026-05-14",
        calendar_dir=tmp_path,
        apply=False,
        prompt_on_write=False,
    )

    assert result["qa_history"][0]["answer"] == "Partially completed."
    assert result["draft"]["reflect_lines"] == ["- Partially completed."]


async def test_run_text_command_opens_weekly_plan(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)
    monkeypatch.setattr("agent.cli.get_default_current_date", lambda: "2026-05-14")

    result = await run_text_command(
        command_text="open weekly plan",
        current_date=None,
        calendar_dir=tmp_path,
        apply=False,
    )

    assert result["document"] == "weekly_plan"
    assert result["path"].endswith("2026-05-11 Weekly Plan.md")
    assert "Existing checkpoint" in result["content"]


async def test_run_text_command_reflect_submenu_can_select_weekly(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")

    async def fake_run_workflow(**kwargs):
        return {"intent": kwargs["intent"]}

    monkeypatch.setattr("agent.cli.run_workflow", fake_run_workflow)

    result = await run_text_command(
        command_text="reflect",
        current_date="2026-05-14",
        calendar_dir=tmp_path,
        apply=False,
    )

    assert result["intent"] == "weekly_reflect"


async def test_run_interactive_session_can_switch_between_open_and_reflect_workflow(
    monkeypatch,
    tmp_path,
) -> None:
    _write_calendar_fixture(tmp_path)
    inputs = iter(["open weekly plan", "", "", "4", "2", "", "exit"])
    actions: list[str] = []

    async def fake_run_workflow(**kwargs):
        actions.append(kwargs["intent"])
        return {"thread_id": "t"}

    def fake_show_document(**kwargs):
        actions.append(f"open:{kwargs['document']}")
        return {"document": kwargs["document"], "path": "x", "content": ""}

    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("agent.cli.run_workflow", fake_run_workflow)
    monkeypatch.setattr("agent.cli.show_document", fake_show_document)
    monkeypatch.setattr("agent.cli.get_default_current_date", lambda: "2099-01-02")

    await run_interactive_session(calendar_dir=tmp_path, apply=False)

    assert actions == ["open:weekly_plan", "weekly_reflect"]
