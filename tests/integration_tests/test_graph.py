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
            "message": "本周重点先放在论文和面试。",
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
                        "reason": "DDL 最近且影响最大。",
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
            "message": "临时任务已按影响和时效整理。",
            "draft": {
                "intent": "temp_plan",
                "structured_temp_tasks": [
                    {
                        "task": "Renew visa",
                        "category": "admin",
                        "urgency": "high",
                        "should_enter_weekly_plan": True,
                        "reason": "有明确时间压力。",
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


async def test_daily_plan_uses_llm_checkpoint_and_meus(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_daily_turn(**kwargs):
        return {
            "status": "ready",
            "message": "今天保持与已有日历时间块一致。",
            "draft": {
                "intent": "daily_plan",
                "current_date": "2026-05-14",
                "checkpoint": "Existing checkpoint",
                "reason": "已有时间块已经为它预留。",
                "calendar_blocks": [
                    "- [ ] Existing checkpoint [startTime:: 09:00] [endTime:: 10:00]"
                ],
                "meu_candidates": [
                    {
                        "action": "Write the first paragraph",
                        "expected_minutes": 30,
                        "verification": "One paragraph is drafted.",
                    },
                    {
                        "action": "List blockers",
                        "expected_minutes": 10,
                        "verification": "A blocker list exists.",
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

    assert result["draft"]["checkpoint"] == "Existing checkpoint"
    assert len(result["draft"]["meu_candidates"]) == 2
    assert "Checkpoint reason:" in result["response"]


async def test_daily_reflect_supports_interrupt_resume(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_daily_reflect_turn(**kwargs):
        qa_history = kwargs["qa_history"]
        if not qa_history:
            return {
                "status": "needs_input",
                "message": "我还缺少今天实际完成情况。",
                "question": "今天最重要的实际进展是什么？",
            }

        assert qa_history[0]["answer"] == "完成了相机 ready 的正文修改。"
        return {
            "status": "ready",
            "message": "已结合你的补充整理复盘。",
            "draft": {
                "intent": "daily_reflect",
                "current_date": "2026-05-14",
                "reflect_lines": [
                    "- 完成了相机 ready 的正文修改。",
                    "- 未完成的是实验复核。",
                    "- 明天继续推进 Existing checkpoint。",
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
    assert interrupt["question"] == "今天最重要的实际进展是什么？"

    resumed = await graph.ainvoke(
        Command(resume="完成了相机 ready 的正文修改。"),
        config,
    )

    assert resumed["draft"]["reflect_lines"][0] == "- 完成了相机 ready 的正文修改。"
    assert "Q&A turns: 1" in resumed["response"]
