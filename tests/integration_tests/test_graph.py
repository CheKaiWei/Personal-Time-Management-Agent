import importlib

import pytest
from langgraph.types import Command

from agent import graph

graph_module = importlib.import_module("agent.graph")

pytestmark = pytest.mark.anyio


def _write_calendar_fixture(tmp_path) -> None:
    (tmp_path / "2026-05 Long-term.univer.md").write_text(
        """
```sheet
{"sheetOrder":["sheet-1"],"sheets":{"sheet-1":{"cellData":{"2":{"0":{"v":"Projects"},"1":{"v":"Tasks"}},"3":{"0":{"v":"Research"},"1":{"v":"Camera ready"},"4":{"v":"P1"},"5":{"v":"E2"},"7":{"v":"6h"}},"4":{"0":{"v":"Career"},"1":{"v":"Interview prep"},"4":{"v":"P1"},"5":{"v":"E2"},"7":{"v":"3h"}}}}}}
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
- [ ] Gym

# Daily Links
[[2026-05-11]]
[[2026-05-12]]
[[2026-05-13]]
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
- [ ] Existing checkpoint [startTime:: 09:00] [endTime:: 10:00]

# Tasks
- [ ] Existing checkpoint
  - [ ] Write one paragraph. Verify: one paragraph exists.

# Notes
- 10:30 blocked by messages

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


async def test_weekly_plan_uses_llm_draft(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_weekly_turn(**kwargs):
        assert kwargs["week_start"] == "2026-05-11"
        return {
            "status": "ready",
            "message": "This week's top work is research and interview prep.",
            "draft": {
                "intent": "weekly_plan",
                "current_date": "2026-05-14",
                "week_start": "2026-05-11",
                "weekly_checkpoints": [
                    {
                        "title": "Research / Camera ready",
                        "row_id": "3",
                        "priority": "P1",
                        "urgency": "E1",
                        "expected_hours": "6h",
                        "reason": "Closest deadline and highest impact.",
                    }
                ],
                "temp_tasks": ["Renew visa"],
                "daily_links": ["2026-05-11", "2026-05-12"],
            },
        }

    monkeypatch.setattr(graph_module, "plan_weekly_turn", fake_plan_weekly_turn)

    result = await graph.ainvoke(
        {
            "intent": "weekly_plan",
            "current_date": "2026-05-14",
            "calendar_dir": str(tmp_path),
        },
        {"configurable": {"thread_id": "week:2026-05-11"}},
    )

    assert result["draft"]["weekly_checkpoints"][0]["title"] == "Research / Camera ready"
    assert "LLM Summary:" in result["response"]


async def test_daily_reflect_supports_interrupt_resume_with_suggested_answers(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_daily_reflect_turn(**kwargs):
        qa_history = kwargs["qa_history"]
        if not qa_history:
            return {
                "status": "needs_input",
                "message": "One completion fact is still missing.",
                "question": "What best describes today's outcome?",
                "suggested_answers": [
                    "Completed as planned.",
                    "Partially completed.",
                    "Mostly interrupted.",
                ],
            }

        assert qa_history[0]["answer"] == "Partially completed."
        return {
            "status": "ready",
            "message": "Daily reflection is ready.",
            "draft": {
                "intent": "daily_reflect",
                "current_date": "2026-05-14",
                "reflect_lines": [
                    "- Partially completed.",
                    "- Experiment rerun is still pending.",
                ],
            },
        }

    monkeypatch.setattr(graph_module, "plan_daily_reflect_turn", fake_plan_daily_reflect_turn)
    config = {"configurable": {"thread_id": "day_reflect:2026-05-14"}}

    first = await graph.ainvoke(
        {
            "intent": "daily_reflect",
            "current_date": "2026-05-14",
            "calendar_dir": str(tmp_path),
        },
        config,
    )

    interrupt = first["__interrupt__"][0].value
    assert interrupt["question"] == "What best describes today's outcome?"
    assert interrupt["suggested_answers"][1] == "Partially completed."

    resumed = await graph.ainvoke(
        Command(resume="Partially completed."),
        config,
    )

    assert resumed["draft"]["reflect_lines"][0] == "- Partially completed."
    assert "Q&A turns: 1" in resumed["response"]


async def test_weekly_reflect_routes_and_formats_adjustments(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_weekly_reflect_turn(**kwargs):
        assert "2026-05-14" in kwargs["week_daily_plans"]
        return {
            "status": "ready",
            "message": "Future schedule needs a small adjustment.",
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

    result = await graph.ainvoke(
        {
            "intent": "weekly_reflect",
            "current_date": "2026-05-14",
            "calendar_dir": str(tmp_path),
        },
        {"configurable": {"thread_id": "week_reflect:2026-05-11"}},
    )

    assert result["draft"]["future_daily_adjustments"][0]["date"] == "2026-05-15"
    assert "Future daily adjustments:" in result["response"]


async def test_long_term_reflect_routes_and_formats_revisions(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_long_term_reflect_turn(**kwargs):
        assert kwargs["long_term_items"][0].row_id == "3"
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

    result = await graph.ainvoke(
        {
            "intent": "long_term_reflect",
            "current_date": "2026-05-14",
            "calendar_dir": str(tmp_path),
        },
        {"configurable": {"thread_id": "long_term:2026-05-14"}},
    )

    assert result["draft"]["revisions"][0]["new_e_level"] == "E1"
    assert "row=3" in result["response"]
