"""Helpers for reading and shaping calendar markdown files."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

LONG_TERM_COLUMNS = 10


@dataclass(frozen=True)
class CalendarPaths:
    """Resolved paths for a single workflow execution."""

    base_dir: Path
    current_date: str
    week_start: str
    long_term_file: Path
    weekly_plan_file: Path
    daily_plan_file: Path


@dataclass(frozen=True)
class LongTermItem:
    """Row-level view of a long-term planning record."""

    row_id: str
    project: str
    task: str
    description: str
    status: str
    p_level: str
    e_level: str
    ddl: str | None
    expected_hours: str | None
    actual_hours: str | None
    notes: str | None


@dataclass(frozen=True)
class WeeklyPlan:
    """Weekly plan sections extracted from markdown."""

    checkpoints: list[str]
    temp_tasks: list[str]
    daily_links: list[str]
    section_order: list[str]
    sections: dict[str, list[str]]


@dataclass(frozen=True)
class DailyPlan:
    """Daily plan sections extracted from markdown."""

    calendar: list[str]
    tasks: list[str]
    notes: list[str]
    reflect: list[str]
    section_order: list[str]
    sections: dict[str, list[str]]


def resolve_calendar_paths(base_dir: Path, current_date: str) -> CalendarPaths:
    """Resolve the files used by the current planning request."""
    parsed_date = datetime.strptime(current_date, "%Y-%m-%d").date()
    week_start = parsed_date - timedelta(days=parsed_date.weekday())
    month_key = parsed_date.strftime("%Y-%m")

    return CalendarPaths(
        base_dir=base_dir,
        current_date=current_date,
        week_start=week_start.isoformat(),
        long_term_file=base_dir / f"{month_key} Long-term.univer.md",
        weekly_plan_file=base_dir / f"{week_start.isoformat()} Weekly Plan.md",
        daily_plan_file=base_dir / f"{current_date}.md",
    )


def parse_weekly_plan(text: str) -> WeeklyPlan:
    """Parse the current weekly plan markdown file."""
    section_order, sections = split_markdown_sections(text)
    checkpoints = extract_checkbox_items(sections.get("Weekly Checkpoint", []))
    temp_tasks = extract_checkbox_items(sections.get("Temp Tasks", []))
    daily_links = []
    for line in text.splitlines():
        match = re.search(r"\[\[(?P<link>[^\]]+)\]\]", line)
        if match:
            daily_links.append(match.group("link"))

    return WeeklyPlan(
        checkpoints=checkpoints,
        temp_tasks=temp_tasks,
        daily_links=daily_links,
        section_order=section_order,
        sections=sections,
    )


def parse_daily_plan(text: str) -> DailyPlan:
    """Parse a daily markdown file into the expected sections."""
    section_order, sections = split_markdown_sections(text)
    calendar = extract_non_empty_lines(sections.get("Calendar", []))
    tasks = extract_non_empty_lines(sections.get("Tasks", []))
    notes = extract_non_empty_lines(sections.get("Notes", []))
    reflect = extract_non_empty_lines(sections.get("Reflect", []))

    return DailyPlan(
        calendar=calendar,
        tasks=tasks,
        notes=notes,
        reflect=reflect,
        section_order=section_order,
        sections=sections,
    )


def parse_long_term_items(text: str) -> list[LongTermItem]:
    """Parse row records from a Univer long-term planning export."""
    workbook = _extract_sheet_payload(text)
    sheet_id = workbook["sheetOrder"][0]
    cell_data = workbook["sheets"][sheet_id]["cellData"]

    items: list[LongTermItem] = []
    current_project = ""
    for row_index in sorted(int(key) for key in cell_data):
        row = cell_data[str(row_index)]
        values = [_read_cell_value(row.get(str(column))) for column in range(LONG_TERM_COLUMNS)]

        project = str(values[0] or "").strip()
        task = str(values[1] or "").strip()
        if project and not task and not any(values[2:]):
            current_project = project
            continue

        if project:
            current_project = project

        if not project:
            project = current_project

        if not task and not any(values[2:]):
            continue

        if task == "Tasks":
            continue

        items.append(
            LongTermItem(
                row_id=str(row_index),
                project=project,
                task=task,
                description=_clean_optional_text(values[2]),
                status=_clean_optional_text(values[3]) or "",
                p_level=_clean_optional_text(values[4]) or "",
                e_level=_clean_optional_text(values[5]) or "",
                ddl=_coerce_date_text(values[6]),
                expected_hours=_clean_optional_text(values[7]),
                actual_hours=_clean_optional_text(values[8]),
                notes=_clean_optional_text(values[9]),
            )
        )

    return items


def split_markdown_sections(text: str) -> tuple[list[str], dict[str, list[str]]]:
    """Split a markdown document into first-level heading sections."""
    section_order: list[str] = []
    sections: dict[str, list[str]] = {}
    current_heading: str | None = None

    for raw_line in text.splitlines():
        match = re.match(r"^#\s+(?P<heading>.+?)\s*$", raw_line)
        if match:
            current_heading = match.group("heading")
            section_order.append(current_heading)
            sections[current_heading] = []
            continue

        if current_heading is None:
            continue

        sections[current_heading].append(raw_line.rstrip())

    return section_order, sections


def render_markdown_sections(section_order: list[str], sections: dict[str, list[str]]) -> str:
    """Render sections back to markdown with stable blank lines."""
    rendered_sections: list[str] = []
    for heading in section_order:
        lines = [line.rstrip() for line in sections.get(heading, [])]
        while lines and not lines[-1]:
            lines.pop()

        rendered = [f"# {heading}"]
        rendered.extend(lines)
        rendered_sections.append("\n".join(rendered).rstrip())

    return "\n\n".join(part for part in rendered_sections if part).rstrip() + "\n"


def extract_checkbox_items(lines: list[str]) -> list[str]:
    """Return checkbox line content without markdown markers."""
    items: list[str] = []
    for line in lines:
        match = re.match(r"^\s*-\s*\[[ xX]\]\s*(?P<item>.+?)\s*$", line)
        if match:
            items.append(match.group("item"))
    return items


def extract_non_empty_lines(lines: list[str]) -> list[str]:
    """Drop blank lines but preserve ordering and indentation."""
    return [line.rstrip() for line in lines if line.strip()]


def _extract_sheet_payload(text: str) -> dict[str, Any]:
    match = re.search(r"```sheet\s*(?P<payload>\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        raise ValueError("Long-term file is missing a ```sheet JSON block.")

    payload = json.loads(match.group("payload"))
    if not isinstance(payload, dict):
        raise ValueError("Long-term sheet payload must be a JSON object.")
    return payload


def _read_cell_value(cell: dict[str, Any] | None) -> Any:
    if not cell or "v" not in cell:
        return None
    return cell["v"]


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _excel_serial_to_date(int(value)).isoformat()
    text = str(value).strip()
    return text or None


def _excel_serial_to_date(serial: int) -> date:
    return date(1899, 12, 30) + timedelta(days=serial)
