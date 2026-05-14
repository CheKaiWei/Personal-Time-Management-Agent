import importlib

import pytest

from agent.cli import MENU_OPTIONS, choose_intent, run_workflow

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


async def test_run_workflow_preview_does_not_write_files(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    async def fake_plan_daily_reflect_turn(**kwargs):
        return {
            "status": "ready",
            "message": "已经根据现有证据生成复盘。",
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
            "message": "今天先推进唯一主线。",
            "draft": {
                "intent": "daily_plan",
                "current_date": "2026-05-14",
                "checkpoint": "Existing checkpoint",
                "reason": "今天不切任务。",
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


async def test_run_workflow_handles_multi_turn_questions(monkeypatch, tmp_path) -> None:
    _write_calendar_fixture(tmp_path)
    answers = iter(["完成了最关键的草稿修改。"])

    async def fake_plan_daily_reflect_turn(**kwargs):
        qa_history = kwargs["qa_history"]
        if not qa_history:
            return {
                "status": "needs_input",
                "message": "我需要你补充事实。",
                "question": "今天最关键的进展是什么？",
            }
        return {
            "status": "ready",
            "message": "已完成多轮复盘。",
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

    assert result["draft"]["reflect_lines"] == ["- 完成了最关键的草稿修改。"]
    assert result["qa_history"][0]["answer"] == "完成了最关键的草稿修改。"
