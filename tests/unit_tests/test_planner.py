from agent.calendar_files import DailyPlan, LongTermItem, WeeklyPlan
from agent.planner import build_daily_plan_draft, build_weekly_plan_draft


def test_build_weekly_plan_draft_uses_at_least_five_checkpoints_when_available() -> None:
    long_term_items = [
        LongTermItem(
            row_id=str(index),
            project="Project",
            task=f"Task {index}",
            description="",
            status="",
            p_level="P1",
            e_level="E1",
            ddl=None,
            expected_hours="2h",
            actual_hours=None,
            notes=None,
        )
        for index in range(1, 7)
    ]
    weekly_plan = WeeklyPlan(
        checkpoints=[],
        temp_tasks=["Renew visa"],
        daily_links=[],
        section_order=["Weekly Checkpoint", "Temp Tasks"],
        sections={"Weekly Checkpoint": [], "Temp Tasks": []},
    )

    draft = build_weekly_plan_draft(
        current_date="2026-05-14",
        week_start="2026-05-11",
        long_term_items=long_term_items,
        weekly_plan=weekly_plan,
    )

    assert len(draft["weekly_checkpoints"]) >= 5
    assert draft["weekly_checkpoints"][0]["title"] == "Project / Task 1"


def test_build_daily_plan_draft_creates_multiple_focus_items_from_weekly_checkpoints() -> None:
    weekly_plan = WeeklyPlan(
        checkpoints=[
            "Research / Camera ready",
            "Career / Interview prep",
            "Health / Training block",
            "Admin / Renew visa",
        ],
        temp_tasks=[],
        daily_links=[],
        section_order=["Weekly Checkpoint", "Temp Tasks"],
        sections={"Weekly Checkpoint": [], "Temp Tasks": []},
    )
    daily_plan = DailyPlan(
        calendar=["- [ ] Existing focus [startTime:: 09:00] [endTime:: 10:00]"],
        tasks=[],
        notes=[],
        reflect=[],
        section_order=["Calendar", "Tasks", "Notes", "Reflect"],
        sections={"Calendar": [], "Tasks": [], "Notes": [], "Reflect": []},
    )

    draft = build_daily_plan_draft(
        current_date="2026-05-14",
        weekly_plan=weekly_plan,
        daily_plan=daily_plan,
    )

    assert len(draft["focus_items"]) == 3
    assert draft["focus_items"][0]["time_block"] == "- [ ] Existing focus [startTime:: 09:00] [endTime:: 10:00]"
    assert draft["focus_items"][1]["checkpoint"] == "Research / Camera ready"
