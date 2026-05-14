import importlib

import pytest

from agent.cli import (
    MENU_OPTIONS,
    choose_intent,
    ensure_backend_ready,
    prompt_for_date,
    run_interactive_session,
    run_workflow,
)

graph_module = importlib.import_module("agent.graph")

pytestmark = pytest.mark.anyio


def _write_calendar_fixture(tmp_path) -> None:
    (tmp_path / "2026-05 Long-term.univer.md").write_text(
        """
```sheet
{"sheetOrder":["sheet-1"],"sheets":{"sheet-1":{"cellData":{"2":{"0":{"v":"Projects"},"1":{"v":"Tasks"}},"3":{"0":{"v":"Research"},"1":{"v":"Camera ready"},"4":{"v":"P1"},"5":{"v":"E1"},"7":{"v":"6h"}}}}}}
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


def test_choose_intent_reads_requested_menu_option(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "3")

    assert choose_intent() == MENU_OPTIONS["3"][1]


def test_prompt_for_date_defaults_to_today(monkeypatch) -> None:
    monkeypatch.setattr("agent.cli.get_default_current_date", lambda: "2099-01-02")
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    assert prompt_for_date() == "2099-01-02"


def test_ensure_backend_ready_rejects_missing_calendar_dir(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="Calendar directory does not exist"):
        ensure_backend_ready(tmp_path / "missing")


async def test_run_workflow_preview_does_not_write_files(monkeypatch, tmp_path) -> None:
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


async def test_run_workflow_apply_writes_files(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_daily_turn(**kwargs):
        return {
            "status": "ready",
            "message": "Draft the main task first.",
            "draft": {
                "intent": "daily_plan",
                "current_date": "2026-05-14",
                "checkpoint": "Existing checkpoint",
                "reason": "Single focus only.",
                "calendar_blocks": [
                    "- [ ] Existing checkpoint [startTime:: 09:00] [endTime:: 10:00]"
                ],
                "meu_candidates": [
                    {
                        "action": "Push the core output",
                        "expected_minutes": 60,
                        "verification": "One artifact exists.",
                    }
                ],
            },
        }

    monkeypatch.setattr(graph_module, "plan_daily_turn", fake_plan_daily_turn)

    await run_workflow(
        intent="daily_plan",
        current_date="2026-05-14",
        calendar_dir=tmp_path,
        apply=True,
        prompt_on_write=False,
    )

    daily_text = (tmp_path / "2026-05-14.md").read_text(encoding="utf-8")
    assert "Push the core output" in daily_text


async def test_run_workflow_revises_until_approved(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)
    review_inputs = iter(["Please make the task more specific", "通过"])
    planning_calls: list[dict[str, object]] = []

    async def fake_plan_daily_turn(**kwargs):
        planning_calls.append(
            {
                "review_feedback_history": list(kwargs.get("review_feedback_history", [])),
                "previous_draft": kwargs.get("previous_draft"),
            }
        )
        if kwargs.get("review_feedback_history"):
            return {
                "status": "ready",
                "message": "Revised draft is ready.",
                "draft": {
                    "intent": "daily_plan",
                    "current_date": "2026-05-14",
                    "checkpoint": "Existing checkpoint",
                    "reason": "Updated after feedback.",
                    "calendar_blocks": [
                        "- [ ] Existing checkpoint [startTime:: 09:00] [endTime:: 10:00]"
                    ],
                    "meu_candidates": [
                        {
                            "action": "Draft the outline and first paragraph",
                            "expected_minutes": 45,
                            "verification": "An outline and one paragraph exist.",
                        }
                    ],
                },
            }

        return {
            "status": "ready",
            "message": "First draft is ready.",
            "draft": {
                "intent": "daily_plan",
                "current_date": "2026-05-14",
                "checkpoint": "Existing checkpoint",
                "reason": "Initial version.",
                "calendar_blocks": [
                    "- [ ] Existing checkpoint [startTime:: 09:00] [endTime:: 10:00]"
                ],
                "meu_candidates": [
                    {
                        "action": "Push the core output",
                        "expected_minutes": 60,
                        "verification": "One artifact exists.",
                    }
                ],
            },
        }

    monkeypatch.setattr(graph_module, "plan_daily_turn", fake_plan_daily_turn)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(review_inputs))

    result = await run_workflow(
        intent="daily_plan",
        current_date="2026-05-14",
        calendar_dir=tmp_path,
        apply=False,
        prompt_on_write=True,
    )

    daily_text = (tmp_path / "2026-05-14.md").read_text(encoding="utf-8")
    assert "Draft the outline and first paragraph" in daily_text
    assert len(planning_calls) == 2
    assert planning_calls[1]["review_feedback_history"] == ["Please make the task more specific"]
    assert planning_calls[1]["previous_draft"] is not None
    assert result["draft"]["meu_candidates"][0]["action"] == "Draft the outline and first paragraph"


async def test_run_workflow_returns_to_menu_from_review(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_daily_turn(**kwargs):
        return {
            "status": "ready",
            "message": "First draft is ready.",
            "draft": {
                "intent": "daily_plan",
                "current_date": "2026-05-14",
                "checkpoint": "Existing checkpoint",
                "reason": "Initial version.",
                "calendar_blocks": [
                    "- [ ] Existing checkpoint [startTime:: 09:00] [endTime:: 10:00]"
                ],
                "meu_candidates": [
                    {
                        "action": "Push the core output",
                        "expected_minutes": 60,
                        "verification": "One artifact exists.",
                    }
                ],
            },
        }

    monkeypatch.setattr(graph_module, "plan_daily_turn", fake_plan_daily_turn)
    monkeypatch.setattr("builtins.input", lambda prompt="": "返回")

    result = await run_workflow(
        intent="daily_plan",
        current_date="2026-05-14",
        calendar_dir=tmp_path,
        apply=False,
        prompt_on_write=True,
    )

    assert result["return_to_menu"] is True
    daily_text = (tmp_path / "2026-05-14.md").read_text(encoding="utf-8")
    assert "Push the core output" not in daily_text


async def test_run_workflow_handles_multi_turn_questions(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)
    answers = iter(["Finished the key draft revision."])

    async def fake_plan_daily_reflect_turn(**kwargs):
        qa_history = kwargs["qa_history"]
        if not qa_history:
            return {
                "status": "needs_input",
                "message": "I need one missing fact.",
                "question": "What was the most important progress today?",
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
    monkeypatch.setattr("agent.cli.build_thread_id", lambda **kwargs: "test-multi-turn")

    result = await run_workflow(
        intent="daily_reflect",
        current_date="2026-05-14",
        calendar_dir=tmp_path,
        apply=False,
        prompt_on_write=False,
    )

    assert result["draft"]["reflect_lines"] == ["- Finished the key draft revision."]
    assert result["qa_history"][0]["answer"] == "Finished the key draft revision."


async def test_run_interactive_session_can_switch_menu(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)
    inputs = iter(["2", "", "", "3", "", "exit"])
    calls: list[str] = []

    async def fake_run_workflow(**kwargs):
        calls.append(kwargs["intent"])
        return {"thread_id": "t"}

    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr("agent.cli.run_workflow", fake_run_workflow)
    monkeypatch.setattr("agent.cli.get_default_current_date", lambda: "2099-01-02")

    await run_interactive_session(calendar_dir=tmp_path, apply=False)

    assert calls == ["temp_plan", "daily_plan"]
