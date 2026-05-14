"""LangGraph workflow for deterministic calendar planning."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Literal

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

if __package__ in {None, ""}:
    src_root = Path(__file__).resolve().parents[1]
    src_root_str = str(src_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)

from agent.calendar_files import (
    DailyPlan,
    LongTermItem,
    WeeklyPlan,
    parse_daily_plan,
    parse_long_term_items,
    parse_weekly_plan,
    resolve_calendar_paths,
)
from agent.planner import (
    build_daily_plan_draft,
    build_daily_reflect_draft,
    build_temp_plan_draft,
    build_weekly_plan_draft,
    format_daily_plan_response,
    format_daily_reflect_response,
    format_temp_plan_response,
    format_weekly_plan_response,
)

Intent = Literal["weekly_plan", "temp_plan", "daily_plan", "daily_reflect"]


class State(TypedDict, total=False):
    """Input and output state for the calendar planning graph."""

    intent: Intent
    current_date: str
    calendar_dir: str
    week_start: str
    long_term_file: str
    weekly_plan_file: str
    daily_plan_file: str
    long_term_items: list[LongTermItem]
    weekly_plan: WeeklyPlan
    daily_plan: DailyPlan
    draft: dict[str, object]
    response: str


def load_context(state: State) -> dict[str, object]:
    """Resolve file paths and read only the files needed by the chosen intent."""
    intent = state["intent"]
    current_date = state.get("current_date") or date.today().isoformat()
    calendar_dir = Path(state.get("calendar_dir") or _default_calendar_dir())
    paths = resolve_calendar_paths(calendar_dir, current_date)

    updates: dict[str, object] = {
        "current_date": current_date,
        "calendar_dir": str(calendar_dir),
        "week_start": paths.week_start,
        "long_term_file": str(paths.long_term_file),
        "weekly_plan_file": str(paths.weekly_plan_file),
        "daily_plan_file": str(paths.daily_plan_file),
        "weekly_plan": _load_weekly_plan(paths.weekly_plan_file),
        "daily_plan": _load_daily_plan(paths.daily_plan_file),
    }

    if intent == "weekly_plan":
        updates["long_term_items"] = _load_long_term_items(paths.long_term_file)

    return updates


def route_intent(state: State) -> Intent:
    """Return the next workflow node name for the current intent."""
    return state["intent"]


def weekly_plan(state: State) -> dict[str, object]:
    """Build a weekly plan preview without writing files."""
    draft = build_weekly_plan_draft(
        current_date=state["current_date"],
        week_start=state["week_start"],
        long_term_items=state.get("long_term_items", []),
        weekly_plan=state["weekly_plan"],
    )
    return {
        "draft": draft,
        "response": format_weekly_plan_response(draft),
    }


def temp_plan(state: State) -> dict[str, object]:
    """Build a temp task structuring preview without writing files."""
    draft = build_temp_plan_draft(state["weekly_plan"])
    return {
        "draft": draft,
        "response": format_temp_plan_response(draft),
    }


def daily_plan(state: State) -> dict[str, object]:
    """Build a daily plan preview without writing files."""
    draft = build_daily_plan_draft(
        current_date=state["current_date"],
        weekly_plan=state["weekly_plan"],
        daily_plan=state["daily_plan"],
    )
    return {
        "draft": draft,
        "response": format_daily_plan_response(draft),
    }


def daily_reflect(state: State) -> dict[str, object]:
    """Build a daily reflection preview without writing files."""
    draft = build_daily_reflect_draft(
        current_date=state["current_date"],
        daily_plan=state["daily_plan"],
    )
    return {
        "draft": draft,
        "response": format_daily_reflect_response(draft),
    }


def _default_calendar_dir() -> str:
    return str(Path(__file__).resolve().parents[3] / "calendar")


def _load_long_term_items(path: Path) -> list[LongTermItem]:
    if not path.exists():
        return []
    return parse_long_term_items(path.read_text(encoding="utf-8"))


def _load_weekly_plan(path: Path) -> WeeklyPlan:
    if not path.exists():
        return WeeklyPlan(
            checkpoints=[],
            temp_tasks=[],
            daily_links=[],
            section_order=["Weekly Checkpoint", "Temp Tasks"],
            sections={"Weekly Checkpoint": [], "Temp Tasks": []},
        )
    return parse_weekly_plan(path.read_text(encoding="utf-8"))


def _load_daily_plan(path: Path) -> DailyPlan:
    if not path.exists():
        return DailyPlan(
            calendar=[],
            tasks=[],
            notes=[],
            reflect=[],
            section_order=["Calendar", "Tasks", "Notes", "Reflect"],
            sections={"Calendar": [], "Tasks": [], "Notes": [], "Reflect": []},
        )
    return parse_daily_plan(path.read_text(encoding="utf-8"))


graph = (
    StateGraph(State)
    .add_node("load_context", load_context)
    .add_node("weekly_plan", weekly_plan)
    .add_node("temp_plan", temp_plan)
    .add_node("daily_plan", daily_plan)
    .add_node("daily_reflect", daily_reflect)
    .add_edge(START, "load_context")
    .add_conditional_edges(
        "load_context",
        route_intent,
        {
            "weekly_plan": "weekly_plan",
            "temp_plan": "temp_plan",
            "daily_plan": "daily_plan",
            "daily_reflect": "daily_reflect",
        },
    )
    .add_edge("weekly_plan", END)
    .add_edge("temp_plan", END)
    .add_edge("daily_plan", END)
    .add_edge("daily_reflect", END)
    .compile(name="Calendar Planning Graph")
)
