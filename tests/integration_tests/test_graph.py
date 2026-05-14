import pytest

from agent import graph

pytestmark = pytest.mark.anyio


def _write_calendar_fixture(tmp_path) -> None:
    (tmp_path / "2026-05 Long-term.univer.md").write_text(
        """
```sheet
{"sheetOrder":["sheet-1"],"sheets":{"sheet-1":{"cellData":{"2":{"0":{"v":"Projects"},"1":{"v":"Tasks"}},"3":{"0":{"v":"Research"},"1":{"v":"Camera ready"},"4":{"v":"P1"},"5":{"v":"E1"},"7":{"v":"6h"}},"4":{"0":{"v":"Career"},"1":{"v":"Interview prep"},"4":{"v":"P1"},"5":{"v":"E2"},"7":{"v":"3h"}},"5":{"0":{"v":"Health"},"1":{"v":"Gym plan"},"4":{"v":"P3"},"5":{"v":"E3"}}}}}}
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


async def test_weekly_plan_route_returns_draft(tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    result = await graph.ainvoke(
        {
            "intent": "weekly_plan",
            "current_date": "2026-05-14",
            "calendar_dir": str(tmp_path),
        }
    )

    assert result["draft"]["intent"] == "weekly_plan"
    assert result["draft"]["weekly_checkpoints"][0]["title"] == "Research / Camera ready"
    assert "Weekly Checkpoint:" in result["response"]


async def test_temp_plan_route_returns_structured_temp_tasks(tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    result = await graph.ainvoke(
        {
            "intent": "temp_plan",
            "current_date": "2026-05-14",
            "calendar_dir": str(tmp_path),
        }
    )

    assert result["draft"]["intent"] == "temp_plan"
    assert result["draft"]["structured_temp_tasks"][0]["category"] == "admin"
    assert "weekly=yes" in result["response"]


async def test_daily_plan_route_returns_checkpoint_and_meus(tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    result = await graph.ainvoke(
        {
            "intent": "daily_plan",
            "current_date": "2026-05-14",
            "calendar_dir": str(tmp_path),
        }
    )

    assert result["draft"]["intent"] == "daily_plan"
    assert result["draft"]["checkpoint"] == "Existing checkpoint"
    assert len(result["draft"]["meu_candidates"]) == 3
    assert "今日 checkpoint" in result["response"]


async def test_daily_plan_prefers_existing_calendar_checkpoint(tmp_path) -> None:
    (tmp_path / "2026-05-11 Weekly Plan.md").write_text(
        """
# Weekly Checkpoint
- [ ] Weekly checkpoint

# Temp Tasks
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "2026-05-14.md").write_text(
        """
# Calendar
- [ ] Calendar checkpoint [startTime:: 09:00] [endTime:: 10:00]

# Tasks

# Notes

# Reflect
""".strip(),
        encoding="utf-8",
    )

    result = await graph.ainvoke(
        {
            "intent": "daily_plan",
            "current_date": "2026-05-14",
            "calendar_dir": str(tmp_path),
        }
    )

    assert result["draft"]["checkpoint"] == "Calendar checkpoint"


async def test_daily_reflect_route_returns_summary(tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    result = await graph.ainvoke(
        {
            "intent": "daily_reflect",
            "current_date": "2026-05-14",
            "calendar_dir": str(tmp_path),
        }
    )

    assert result["draft"]["intent"] == "daily_reflect"
    assert any("安排 1 个时间块" in line for line in result["draft"]["reflect_lines"])
    assert result["draft"]["reflect_lines"][-1].endswith("Existing checkpoint。")
    assert "已生成日复盘草案" in result["response"]
