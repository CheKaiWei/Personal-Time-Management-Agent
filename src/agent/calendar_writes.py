"""Patch builders and file writers for calendar documents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.calendar_files import (
    LONG_TERM_E_LEVEL_COLUMN,
    LONG_TERM_NOTES_COLUMN,
    DailyPlan,
    WeeklyPlan,
    default_daily_plan,
    parse_long_term_workbook,
    render_long_term_workbook,
    render_markdown_sections,
    resolve_calendar_paths,
)


@dataclass(frozen=True)
class FilePatch:
    """A concrete file write prepared from a planning draft."""

    path: Path
    content: str
    summary: str


def build_weekly_plan_patches(
    *,
    calendar_dir: Path,
    current_date: str,
    weekly_plan: WeeklyPlan,
    draft: dict[str, Any],
) -> list[FilePatch]:
    """Build the weekly plan patch set, including missing daily templates."""
    paths = resolve_calendar_paths(calendar_dir, current_date)
    checkpoints = [f"- [ ] {item['title']}" for item in draft["weekly_checkpoints"]]
    temp_tasks = [f"- [ ] {task}" for task in draft["temp_tasks"]]
    daily_links = [f"[[{link}]]" for link in draft["daily_links"]]
    adjustment_log = [f"- {current_date}: weekly plan initialized from long-term items."]

    weekly_content = _render_weekly_plan(
        weekly_plan=weekly_plan,
        checkpoints=checkpoints,
        temp_tasks=temp_tasks,
        daily_links=daily_links,
        adjustment_log=adjustment_log,
    )
    patches = [
        FilePatch(
            path=paths.weekly_plan_file,
            content=weekly_content,
            summary="Update weekly plan checkpoints, temp tasks, and day links.",
        )
    ]

    for link in draft["daily_links"]:
        daily_path = calendar_dir / f"{link}.md"
        if daily_path.exists():
            continue
        patches.append(
            FilePatch(
                path=daily_path,
                content=_render_daily_template(),
                summary=f"Create daily template for {link}.",
            )
        )

    return patches


def build_temp_plan_patches(
    *,
    calendar_dir: Path,
    current_date: str,
    weekly_plan: WeeklyPlan,
    draft: dict[str, Any],
) -> list[FilePatch]:
    """Build the patch that rewrites Temp Tasks as structured entries."""
    paths = resolve_calendar_paths(calendar_dir, current_date)
    temp_tasks = [
        (
            f"- [ ] {item['task']} | category: {item['category']} | "
            f"urgency: {item['urgency']} | weekly: {'yes' if item['should_enter_weekly_plan'] else 'no'}"
        )
        for item in draft["structured_temp_tasks"]
    ]

    weekly_content = _render_weekly_plan(
        weekly_plan=weekly_plan,
        checkpoints=weekly_plan.sections.get("Weekly Checkpoint", []),
        temp_tasks=temp_tasks,
        daily_links=[f"[[{link}]]" for link in weekly_plan.daily_links],
        adjustment_log=weekly_plan.sections.get("Adjustment Log", []),
    )
    return [
        FilePatch(
            path=paths.weekly_plan_file,
            content=weekly_content,
            summary="Rewrite Temp Tasks with structured metadata.",
        )
    ]


def build_daily_plan_patches(
    *,
    calendar_dir: Path,
    current_date: str,
    daily_plan: DailyPlan,
    draft: dict[str, Any],
) -> list[FilePatch]:
    """Build the patch that writes today's calendar and tasks."""
    paths = resolve_calendar_paths(calendar_dir, current_date)
    focus_items = draft.get("focus_items") or _build_legacy_focus_items(draft)
    task_lines: list[str] = []

    for focus in focus_items:
        task_lines.append(f"- [ ] {focus['checkpoint']}")
        task_lines.extend(
            f"  - [ ] {item['action']}. Verify: {item['verification']}"
            for item in focus["meu_candidates"]
        )

    content = _render_daily_plan(
        daily_plan=daily_plan,
        calendar_lines=[focus["time_block"] for focus in focus_items],
        task_lines=task_lines,
        note_lines=daily_plan.sections.get("Notes", []),
        reflect_lines=daily_plan.sections.get("Reflect", []),
    )
    return [
        FilePatch(
            path=paths.daily_plan_file,
            content=content,
            summary="Update today's Calendar and Tasks sections.",
        )
    ]


def build_daily_reflect_patches(
    *,
    calendar_dir: Path,
    current_date: str,
    daily_plan: DailyPlan,
    draft: dict[str, Any],
) -> list[FilePatch]:
    """Build the patch that writes today's reflection section."""
    paths = resolve_calendar_paths(calendar_dir, current_date)
    content = _render_daily_plan(
        daily_plan=daily_plan,
        calendar_lines=daily_plan.sections.get("Calendar", []),
        task_lines=daily_plan.sections.get("Tasks", []),
        note_lines=daily_plan.sections.get("Notes", []),
        reflect_lines=draft["reflect_lines"],
    )
    return [
        FilePatch(
            path=paths.daily_plan_file,
            content=content,
            summary="Update today's Reflect section.",
        )
    ]


def build_weekly_reflect_patches(
    *,
    calendar_dir: Path,
    current_date: str,
    weekly_plan: WeeklyPlan,
    week_daily_plans: dict[str, DailyPlan],
    draft: dict[str, Any],
) -> list[FilePatch]:
    """Build patch sets for future daily-calendar adjustments and weekly logs."""
    paths = resolve_calendar_paths(calendar_dir, current_date)
    adjustment_log = _merge_unique_lines(
        weekly_plan.sections.get("Adjustment Log", []),
        draft["adjustment_log_lines"],
    )
    weekly_content = _render_weekly_plan(
        weekly_plan=weekly_plan,
        checkpoints=weekly_plan.sections.get("Weekly Checkpoint", []),
        temp_tasks=weekly_plan.sections.get("Temp Tasks", []),
        daily_links=[f"[[{link}]]" for link in weekly_plan.daily_links],
        adjustment_log=adjustment_log,
    )

    patches = [
        FilePatch(
            path=paths.weekly_plan_file,
            content=weekly_content,
            summary="Append weekly adjustment logs.",
        )
    ]

    for adjustment in draft["future_daily_adjustments"]:
        target_date = adjustment["date"]
        daily_plan = week_daily_plans.get(target_date) or default_daily_plan()
        content = _render_daily_plan(
            daily_plan=daily_plan,
            calendar_lines=adjustment["calendar_blocks"],
            task_lines=daily_plan.sections.get("Tasks", []),
            note_lines=daily_plan.sections.get("Notes", []),
            reflect_lines=daily_plan.sections.get("Reflect", []),
        )
        patches.append(
            FilePatch(
                path=calendar_dir / f"{target_date}.md",
                content=content,
                summary=f"Adjust future Calendar blocks for {target_date}.",
            )
        )

    return patches


def build_long_term_reflect_patches(
    *,
    calendar_dir: Path,
    current_date: str,
    draft: dict[str, Any],
) -> list[FilePatch]:
    """Build the patch that updates only long-term E levels and notes."""
    paths = resolve_calendar_paths(calendar_dir, current_date)
    if not paths.long_term_file.exists():
        raise RuntimeError(f"Long-term file does not exist: {paths.long_term_file}")
    if not draft["revisions"]:
        return []

    original_text = paths.long_term_file.read_text(encoding="utf-8")
    workbook = parse_long_term_workbook(original_text)
    sheet_id = workbook["sheetOrder"][0]
    cell_data = workbook["sheets"][sheet_id]["cellData"]

    for revision in draft["revisions"]:
        row = cell_data.setdefault(str(revision["row_id"]), {})
        _set_sheet_text_cell(row, LONG_TERM_E_LEVEL_COLUMN, revision["new_e_level"])
        if revision.get("note_append"):
            existing_note = _read_sheet_text_cell(row, LONG_TERM_NOTES_COLUMN)
            merged_note = _append_note(existing_note, current_date, revision["note_append"])
            _set_sheet_text_cell(row, LONG_TERM_NOTES_COLUMN, merged_note)

    return [
        FilePatch(
            path=paths.long_term_file,
            content=render_long_term_workbook(original_text, workbook),
            summary="Update long-term E levels and notes only.",
        )
    ]


def apply_file_patches(patches: list[FilePatch]) -> None:
    """Write every prepared patch to disk."""
    for patch in patches:
        patch.path.parent.mkdir(parents=True, exist_ok=True)
        patch.path.write_text(patch.content, encoding="utf-8")


def _render_weekly_plan(
    *,
    weekly_plan: WeeklyPlan,
    checkpoints: list[str],
    temp_tasks: list[str],
    daily_links: list[str],
    adjustment_log: list[str],
) -> str:
    section_order = _merge_section_order(
        required_order=["Weekly Checkpoint", "Temp Tasks", "Daily Links", "Adjustment Log"],
        existing_order=weekly_plan.section_order,
    )
    sections = {heading: list(weekly_plan.sections.get(heading, [])) for heading in section_order}
    sections["Weekly Checkpoint"] = checkpoints
    sections["Temp Tasks"] = temp_tasks
    sections["Daily Links"] = daily_links
    sections["Adjustment Log"] = adjustment_log
    return render_markdown_sections(section_order, sections)


def _render_daily_plan(
    *,
    daily_plan: DailyPlan,
    calendar_lines: list[str],
    task_lines: list[str],
    note_lines: list[str],
    reflect_lines: list[str],
) -> str:
    section_order = _merge_section_order(
        required_order=["Calendar", "Tasks", "Notes", "Reflect"],
        existing_order=daily_plan.section_order,
    )
    sections = {heading: list(daily_plan.sections.get(heading, [])) for heading in section_order}
    sections["Calendar"] = list(calendar_lines)
    sections["Tasks"] = list(task_lines)
    sections["Notes"] = list(note_lines)
    sections["Reflect"] = list(reflect_lines)
    return render_markdown_sections(section_order, sections)


def _render_daily_template() -> str:
    return render_markdown_sections(
        ["Calendar", "Tasks", "Notes", "Reflect"],
        {"Calendar": [], "Tasks": [], "Notes": [], "Reflect": []},
    )


def _build_legacy_focus_items(draft: dict[str, Any]) -> list[dict[str, Any]]:
    checkpoint = str(draft.get("checkpoint", "")).strip()
    if not checkpoint:
        return []
    return [
        {
            "checkpoint": checkpoint,
            "time_block": (
                draft.get("calendar_blocks", ["- [ ] " + checkpoint])[0]
                if draft.get("calendar_blocks")
                else f"- [ ] {checkpoint}"
            ),
            "meu_candidates": draft.get("meu_candidates", []),
        }
    ]


def _merge_section_order(*, required_order: list[str], existing_order: list[str]) -> list[str]:
    ordered = list(required_order)
    for heading in existing_order:
        if heading not in ordered:
            ordered.append(heading)
    return ordered


def _merge_unique_lines(existing_lines: list[str], new_lines: list[str]) -> list[str]:
    merged = list(existing_lines)
    seen = {line.strip() for line in existing_lines if line.strip()}
    for line in new_lines:
        normalized = line.strip()
        if not normalized or normalized in seen:
            continue
        merged.append(line)
        seen.add(normalized)
    return merged


def _read_sheet_text_cell(row: dict[str, Any], column_index: int) -> str:
    cell = row.get(str(column_index))
    value = cell.get("v") if isinstance(cell, dict) else None
    return str(value).strip() if value is not None else ""


def _set_sheet_text_cell(row: dict[str, Any], column_index: int, value: str) -> None:
    cell = dict(row.get(str(column_index), {}))
    cell["v"] = value
    cell["t"] = 1
    row[str(column_index)] = cell


def _append_note(existing_note: str, current_date: str, note_append: str) -> str:
    clean_note = note_append.strip()
    if not clean_note:
        return existing_note
    stamped_note = f"{current_date}: {clean_note}"
    if not existing_note:
        return stamped_note
    if stamped_note in existing_note:
        return existing_note
    return f"{existing_note}\n{stamped_note}"
