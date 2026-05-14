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
{"sheetOrder":["sheet-1"],"sheets":{"sheet-1":{"cellData":{"2":{"0":{"v":"Projects"},"1":{"v":"Tasks"}},"3":{"0":{"v":"Research"},"1":{"v":"Camera ready"},"4":{"v":"P1"},"5":{"v":"E1"},"7":{"v":"6h"}},"4":{"0":{"v":"Career"},"1":{"v":"Interview prep"},"4":{"v":"P1"},"5":{"v":"E2"},"7":{"v":"3h"}}}}}}
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

[[2026-05-11]]
[[2026-05-12]]
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


async def test_temp_plan_uses_llm_structuring(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_temp_turn(**kwargs):
        return {
            "status": "ready",
            "message": "Temp tasks are structured by urgency.",
            "draft": {
                "intent": "temp_plan",
                "structured_temp_tasks": [
                    {
                        "task": "Renew visa",
                        "category": "admin",
                        "urgency": "high",
                        "should_enter_weekly_plan": True,
                        "reason": "Time-sensitive document work.",
                    }
                ],
            },
        }

    monkeypatch.setattr(graph_module, "plan_temp_turn", fake_plan_temp_turn)

    result = await graph.ainvoke(
        {
            "intent": "temp_plan",
            "current_date": "2026-05-14",
            "calendar_dir": str(tmp_path),
        },
        {"configurable": {"thread_id": "temp:2026-05-14"}},
    )

    assert result["draft"]["structured_temp_tasks"][0]["category"] == "admin"
    assert "reason=" in result["response"]


async def test_daily_plan_uses_llm_focus_items_and_meus(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_daily_turn(**kwargs):
        return {
            "status": "ready",
            "message": "Spread today's effort across weekly checkpoints.",
            "draft": {
                "intent": "daily_plan",
                "current_date": "2026-05-14",
                "focus_items": [
                    {
                        "checkpoint": "Research / Camera ready",
                        "reason": "Research is the highest urgency item.",
                        "time_block": "- [ ] Research / Camera ready [startTime:: 09:00] [endTime:: 10:00]",
                        "meu_candidates": [
                            {
                                "action": "Draft the figure checklist",
                                "expected_minutes": 30,
                                "verification": "A checklist exists.",
                            }
                        ],
                    },
                    {
                        "checkpoint": "Career / Interview prep",
                        "reason": "Keep interview preparation moving.",
                        "time_block": "- [ ] Career / Interview prep [startTime:: 14:00] [endTime:: 15:00]",
                        "meu_candidates": [
                            {
                                "action": "Answer three mock questions",
                                "expected_minutes": 30,
                                "verification": "Three answers exist.",
                            }
                        ],
                    },
                ],
            },
        }

    monkeypatch.setattr(graph_module, "plan_daily_turn", fake_plan_daily_turn)

    result = await graph.ainvoke(
        {
            "intent": "daily_plan",
            "current_date": "2026-05-14",
            "calendar_dir": str(tmp_path),
        },
        {"configurable": {"thread_id": "day:2026-05-14"}},
    )

    assert len(result["draft"]["focus_items"]) == 2
    assert result["draft"]["focus_items"][0]["checkpoint"] == "Research / Camera ready"
    assert "Today's focus items:" in result["response"]


async def test_daily_reflect_supports_interrupt_resume(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_daily_reflect_turn(**kwargs):
        qa_history = kwargs["qa_history"]
        if not qa_history:
            return {
                "status": "needs_input",
                "message": "One completion fact is still missing.",
                "question": "What was the most important actual progress today?",
            }

        assert qa_history[0]["answer"] == "Finished the camera-ready revision."
        return {
            "status": "ready",
            "message": "Daily reflection is ready.",
            "draft": {
                "intent": "daily_reflect",
                "current_date": "2026-05-14",
                "reflect_lines": [
                    "- Finished the camera-ready revision.",
                    "- Experiment rerun is still pending.",
                    "- Tomorrow continue Existing checkpoint.",
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
    assert interrupt["question"] == "What was the most important actual progress today?"

    resumed = await graph.ainvoke(
        Command(resume="Finished the camera-ready revision."),
        config,
    )

    assert resumed["draft"]["reflect_lines"][0] == "- Finished the camera-ready revision."
    assert "Q&A turns: 1" in resumed["response"]
