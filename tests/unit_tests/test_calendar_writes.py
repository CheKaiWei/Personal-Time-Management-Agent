from agent.calendar_files import (
    parse_daily_plan,
    parse_long_term_workbook,
    parse_weekly_plan,
)
from agent.calendar_writes import (
    apply_file_patches,
    build_daily_plan_patches,
    build_daily_reflect_patches,
    build_long_term_reflect_patches,
    build_temp_plan_patches,
    build_weekly_plan_patches,
    build_weekly_reflect_patches,
)


def test_build_weekly_plan_patches_creates_week_and_missing_days(tmp_path) -> None:
    weekly_plan = parse_weekly_plan(
        """
# Weekly Checkpoint
- [ ] Old checkpoint

# Temp Tasks
- [ ] Renew visa
""".strip()
    )

    patches = build_weekly_plan_patches(
        calendar_dir=tmp_path,
        current_date="2026-05-14",
        weekly_plan=weekly_plan,
        draft={
            "weekly_checkpoints": [
                {"title": "Research / Camera ready"},
                {"title": "Career / Interview prep"},
            ],
            "temp_tasks": ["Renew visa"],
            "daily_links": ["2026-05-11", "2026-05-12"],
        },
    )
    apply_file_patches(patches)

    weekly_text = (tmp_path / "2026-05-11 Weekly Plan.md").read_text(encoding="utf-8")

    assert "# Daily Links" in weekly_text
    assert "- [ ] Research / Camera ready" in weekly_text
    assert "[[2026-05-12]]" in weekly_text
    assert (tmp_path / "2026-05-12.md").exists()


def test_build_temp_plan_patches_rewrites_temp_tasks(tmp_path) -> None:
    weekly_path = tmp_path / "2026-05-11 Weekly Plan.md"
    weekly_path.write_text(
        """
# Weekly Checkpoint
- [ ] Existing checkpoint

# Temp Tasks
- [ ] Renew visa

# Daily Links
[[2026-05-11]]
""".strip(),
        encoding="utf-8",
    )
    weekly_plan = parse_weekly_plan(weekly_path.read_text(encoding="utf-8"))

    patches = build_temp_plan_patches(
        calendar_dir=tmp_path,
        current_date="2026-05-14",
        weekly_plan=weekly_plan,
        draft={
            "structured_temp_tasks": [
                {
                    "task": "Renew visa",
                    "category": "admin",
                    "urgency": "high",
                    "should_enter_weekly_plan": True,
                }
            ]
        },
    )
    apply_file_patches(patches)

    weekly_text = weekly_path.read_text(encoding="utf-8")
    assert "category: admin" in weekly_text
    assert "weekly: yes" in weekly_text


def test_build_daily_plan_patches_updates_multiple_focus_items(tmp_path) -> None:
    daily_path = tmp_path / "2026-05-14.md"
    daily_path.write_text(
        """
# Calendar

# Tasks

# Notes
- Existing note

# Reflect
""".strip(),
        encoding="utf-8",
    )
    daily_plan = parse_daily_plan(daily_path.read_text(encoding="utf-8"))

    patches = build_daily_plan_patches(
        calendar_dir=tmp_path,
        current_date="2026-05-14",
        daily_plan=daily_plan,
        draft={
            "focus_items": [
                {
                    "checkpoint": "Research / Camera ready",
                    "time_block": "- [ ] Research / Camera ready [startTime:: 09:00] [endTime:: 10:30]",
                    "meu_candidates": [
                        {
                            "action": "Draft the figure checklist",
                            "verification": "A checklist file exists",
                        }
                    ],
                },
                {
                    "checkpoint": "Career / Interview prep",
                    "time_block": "- [ ] Career / Interview prep [startTime:: 14:00] [endTime:: 15:00]",
                    "meu_candidates": [
                        {
                            "action": "Answer three mock questions",
                            "verification": "Three written answers exist",
                        }
                    ],
                },
            ]
        },
    )
    apply_file_patches(patches)

    daily_text = daily_path.read_text(encoding="utf-8")
    assert "Research / Camera ready [startTime:: 09:00]" in daily_text
    assert "- [ ] Career / Interview prep" in daily_text
    assert "  - [ ] Draft the figure checklist. Verify: A checklist file exists" in daily_text
    assert "  - [ ] Answer three mock questions. Verify: Three written answers exist" in daily_text
    assert "- Existing note" in daily_text


def test_build_daily_reflect_patches_updates_only_reflect(tmp_path) -> None:
    daily_path = tmp_path / "2026-05-14.md"
    daily_path.write_text(
        """
# Calendar
- [ ] Existing checkpoint [startTime:: 09:00] [endTime:: 10:00]

# Tasks
- [ ] Existing checkpoint

# Notes
- Existing note

# Reflect
""".strip(),
        encoding="utf-8",
    )
    daily_plan = parse_daily_plan(daily_path.read_text(encoding="utf-8"))

    patches = build_daily_reflect_patches(
        calendar_dir=tmp_path,
        current_date="2026-05-14",
        daily_plan=daily_plan,
        draft={"reflect_lines": ["- Today progressed steadily.", "- Tomorrow continue the same checkpoint."]},
    )
    apply_file_patches(patches)

    daily_text = daily_path.read_text(encoding="utf-8")
    assert "- Today progressed steadily." in daily_text
    assert "- Existing note" in daily_text


def test_build_weekly_reflect_patches_updates_log_and_future_calendars(tmp_path) -> None:
    weekly_path = tmp_path / "2026-05-11 Weekly Plan.md"
    weekly_path.write_text(
        """
# Weekly Checkpoint
- [ ] Research / Camera ready

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
    future_daily_path = tmp_path / "2026-05-15.md"
    future_daily_path.write_text(
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

    weekly_plan = parse_weekly_plan(weekly_path.read_text(encoding="utf-8"))
    week_daily_plans = {
        "2026-05-15": parse_daily_plan(future_daily_path.read_text(encoding="utf-8")),
    }
    patches = build_weekly_reflect_patches(
        calendar_dir=tmp_path,
        current_date="2026-05-14",
        weekly_plan=weekly_plan,
        week_daily_plans=week_daily_plans,
        draft={
            "adjustment_log_lines": ["- 2026-05-14: moved interview prep to tomorrow afternoon."],
            "future_daily_adjustments": [
                {
                    "date": "2026-05-15",
                    "reason": "Recovered time after today's progress.",
                    "calendar_blocks": [
                        "- [ ] Career / Interview prep [startTime:: 14:00] [endTime:: 15:30]"
                    ],
                }
            ],
        },
    )
    apply_file_patches(patches)

    weekly_text = weekly_path.read_text(encoding="utf-8")
    future_daily_text = future_daily_path.read_text(encoding="utf-8")
    assert "moved interview prep to tomorrow afternoon" in weekly_text
    assert "Career / Interview prep [startTime:: 14:00]" in future_daily_text
    assert "- [ ] Keep this task" in future_daily_text
    assert "- Future note" in future_daily_text


def test_build_long_term_reflect_patches_updates_only_e_and_notes(tmp_path) -> None:
    long_term_path = tmp_path / "2026-05 Long-term.univer.md"
    long_term_path.write_text(
        """
```sheet
{"sheetOrder":["sheet-1"],"sheets":{"sheet-1":{"cellData":{"2":{"0":{"v":"Projects"},"1":{"v":"Tasks"}},"3":{"0":{"v":"Research"},"1":{"v":"Camera ready"},"4":{"v":"P1"},"5":{"v":"E2"},"9":{"v":"Need figures"}}}}}}
```
```multiSheet
{"tabs":[]}
```
""".strip(),
        encoding="utf-8",
    )

    patches = build_long_term_reflect_patches(
        calendar_dir=tmp_path,
        current_date="2026-05-14",
        draft={
            "revisions": [
                {
                    "row_id": "3",
                    "new_e_level": "E1",
                    "note_append": "Camera ready entered final risk window.",
                }
            ]
        },
    )
    apply_file_patches(patches)

    workbook = parse_long_term_workbook(long_term_path.read_text(encoding="utf-8"))
    row = workbook["sheets"]["sheet-1"]["cellData"]["3"]
    assert row["5"]["v"] == "E1"
    assert row["9"]["v"] == "Need figures\n2026-05-14: Camera ready entered final risk window."
    assert row["4"]["v"] == "P1"
    assert row["1"]["v"] == "Camera ready"
