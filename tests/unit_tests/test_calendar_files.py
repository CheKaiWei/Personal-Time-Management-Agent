from pathlib import Path

from agent.calendar_files import (
    extract_checkbox_items,
    parse_daily_plan,
    parse_long_term_items,
    parse_weekly_plan,
    render_markdown_sections,
    resolve_calendar_paths,
    split_markdown_sections,
)


def test_resolve_calendar_paths_uses_monday_week_start() -> None:
    paths = resolve_calendar_paths(Path("calendar"), "2026-05-14")

    assert paths.week_start == "2026-05-11"
    assert paths.weekly_plan_file == Path("calendar") / "2026-05-11 Weekly Plan.md"
    assert paths.daily_plan_file == Path("calendar") / "2026-05-14.md"
    assert paths.long_term_file == Path("calendar") / "2026-05 Long-term.univer.md"


def test_parse_weekly_plan_extracts_sections() -> None:
    weekly_plan = parse_weekly_plan(
        """
# Weekly Checkpoint
- [ ] Ship weekly demo
- [ ] Draft paper outline

# Temp Tasks
- [ ] Renew visa

[[2026-05-10]]
[[2026-05-11]]
""".strip()
    )

    assert weekly_plan.checkpoints == ["Ship weekly demo", "Draft paper outline"]
    assert weekly_plan.temp_tasks == ["Renew visa"]
    assert weekly_plan.daily_links == ["2026-05-10", "2026-05-11"]


def test_parse_daily_plan_reads_expected_sections() -> None:
    daily_plan = parse_daily_plan(
        """
# Calendar
- [ ] Deep work [startTime:: 09:00] [endTime:: 10:30]

# Tasks
- [ ] Deep work
  - [ ] Write intro. Verify: one paragraph drafted.

# Notes
- 11:00 blocked by messages

# Reflect
- Finished half of the draft
""".strip()
    )

    assert daily_plan.calendar == [
        "- [ ] Deep work [startTime:: 09:00] [endTime:: 10:30]"
    ]
    assert daily_plan.tasks[1] == "  - [ ] Write intro. Verify: one paragraph drafted."
    assert daily_plan.notes == ["- 11:00 blocked by messages"]
    assert daily_plan.reflect == ["- Finished half of the draft"]


def test_parse_long_term_items_reads_tabular_rows() -> None:
    text = """
```sheet
{"sheetOrder":["sheet-1"],"sheets":{"sheet-1":{"cellData":{"2":{"0":{"v":"Projects"},"1":{"v":"Tasks"}},"3":{"0":{"v":"Research"},"1":{"v":"Camera ready"},"4":{"v":"P1"},"5":{"v":"E1"},"6":{"v":46174},"7":{"v":"6h"},"9":{"v":"Need figures"}},"4":{"1":{"v":"Experiment rerun"},"4":{"v":"P2"},"5":{"v":"E2"},"6":{"v":"2026-06-01"}}}}}}
```
""".strip()

    items = parse_long_term_items(text)

    assert [item.task for item in items] == ["Camera ready", "Experiment rerun"]
    assert items[0].project == "Research"
    assert items[0].ddl == "2026-06-01"
    assert items[0].expected_hours == "6h"
    assert items[1].project == "Research"
    assert items[1].ddl == "2026-06-01"


def test_section_round_trip_keeps_structure() -> None:
    section_order, sections = split_markdown_sections(
        """
# Calendar
- [ ] Focus block

# Reflect
- Good day
""".strip()
    )

    rendered = render_markdown_sections(section_order, sections)

    assert rendered == "# Calendar\n- [ ] Focus block\n\n# Reflect\n- Good day\n"
    assert extract_checkbox_items(sections["Calendar"]) == ["Focus block"]
