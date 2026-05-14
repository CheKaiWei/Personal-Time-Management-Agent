"""LangGraph workflow for LLM-driven calendar planning."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
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
    build_week_dates,
    default_daily_plan,
    default_weekly_plan,
    parse_daily_plan,
    parse_long_term_items,
    parse_weekly_plan,
    resolve_calendar_paths,
)
from agent.planner import (
    format_daily_plan_response,
    format_daily_reflect_response,
    format_long_term_reflect_response,
    format_temp_plan_response,
    format_weekly_plan_response,
    format_weekly_reflect_response,
    plan_daily_reflect_turn,
    plan_daily_turn,
    plan_long_term_reflect_turn,
    plan_temp_turn,
    plan_weekly_reflect_turn,
    plan_weekly_turn,
)

Intent = Literal[
    "weekly_plan",
    "temp_plan",
    "daily_plan",
    "daily_reflect",
    "weekly_reflect",
    "long_term_reflect",
]


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
    week_daily_plans: dict[str, DailyPlan]
    qa_history: list[dict[str, str]]
    review_feedback_history: list[str]
    previous_draft: dict[str, object]
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
        "qa_history": state.get("qa_history", []),
        "review_feedback_history": state.get("review_feedback_history", []),
        "previous_draft": state.get("previous_draft"),
    }

    if intent in {"weekly_plan", "long_term_reflect"}:
        updates["long_term_items"] = _load_long_term_items(paths.long_term_file)

    if intent == "weekly_reflect":
        updates["week_daily_plans"] = _load_week_daily_plans(calendar_dir, paths.week_start)

    return updates


def route_intent(state: State) -> Intent:
    """Return the next workflow node name for the current intent."""
    return state["intent"]


async def weekly_plan(state: State) -> dict[str, object] | Command[str]:
    """Build a weekly plan draft with LLM-driven clarification when needed."""
    decision = await plan_weekly_turn(
        current_date=state["current_date"],
        week_start=state["week_start"],
        long_term_items=state.get("long_term_items", []),
        weekly_plan=state["weekly_plan"],
        qa_history=state.get("qa_history", []),
        review_feedback_history=state.get("review_feedback_history", []),
        previous_draft=state.get("previous_draft"),
    )
    return _handle_llm_decision(
        state=state,
        node_name="weekly_plan",
        decision=decision,
        formatter=format_weekly_plan_response,
    )


async def temp_plan(state: State) -> dict[str, object] | Command[str]:
    """Build a temp task structuring draft with LLM-driven clarification."""
    decision = await plan_temp_turn(
        weekly_plan=state["weekly_plan"],
        qa_history=state.get("qa_history", []),
        review_feedback_history=state.get("review_feedback_history", []),
        previous_draft=state.get("previous_draft"),
    )
    return _handle_llm_decision(
        state=state,
        node_name="temp_plan",
        decision=decision,
        formatter=format_temp_plan_response,
    )


async def daily_plan(state: State) -> dict[str, object] | Command[str]:
    """Build a daily plan draft with LLM-driven clarification."""
    decision = await plan_daily_turn(
        current_date=state["current_date"],
        weekly_plan=state["weekly_plan"],
        daily_plan=state["daily_plan"],
        qa_history=state.get("qa_history", []),
        review_feedback_history=state.get("review_feedback_history", []),
        previous_draft=state.get("previous_draft"),
    )
    return _handle_llm_decision(
        state=state,
        node_name="daily_plan",
        decision=decision,
        formatter=format_daily_plan_response,
    )


async def daily_reflect(state: State) -> dict[str, object] | Command[str]:
    """Build a daily reflection draft with LLM-driven clarification."""
    decision = await plan_daily_reflect_turn(
        current_date=state["current_date"],
        daily_plan=state["daily_plan"],
        qa_history=state.get("qa_history", []),
        review_feedback_history=state.get("review_feedback_history", []),
        previous_draft=state.get("previous_draft"),
    )
    return _handle_llm_decision(
        state=state,
        node_name="daily_reflect",
        decision=decision,
        formatter=format_daily_reflect_response,
    )


async def weekly_reflect(state: State) -> dict[str, object] | Command[str]:
    """Build a weekly adjustment draft from execution evidence so far."""
    decision = await plan_weekly_reflect_turn(
        current_date=state["current_date"],
        week_start=state["week_start"],
        weekly_plan=state["weekly_plan"],
        week_daily_plans=state.get("week_daily_plans", {}),
        qa_history=state.get("qa_history", []),
        review_feedback_history=state.get("review_feedback_history", []),
        previous_draft=state.get("previous_draft"),
    )
    return _handle_llm_decision(
        state=state,
        node_name="weekly_reflect",
        decision=decision,
        formatter=format_weekly_reflect_response,
    )


async def long_term_reflect(state: State) -> dict[str, object] | Command[str]:
    """Build a long-term urgency update draft with strict write boundaries."""
    decision = await plan_long_term_reflect_turn(
        current_date=state["current_date"],
        week_start=state["week_start"],
        weekly_plan=state["weekly_plan"],
        long_term_items=state.get("long_term_items", []),
        qa_history=state.get("qa_history", []),
        review_feedback_history=state.get("review_feedback_history", []),
        previous_draft=state.get("previous_draft"),
    )
    return _handle_llm_decision(
        state=state,
        node_name="long_term_reflect",
        decision=decision,
        formatter=format_long_term_reflect_response,
    )


def _handle_llm_decision(
    *,
    state: State,
    node_name: str,
    decision: dict[str, Any],
    formatter,
) -> dict[str, object] | Command[str]:
    qa_history = list(state.get("qa_history", []))
    if decision["status"] == "needs_input":
        question = str(decision["question"]).strip()
        interrupt_payload: dict[str, object] = {
            "intent": state["intent"],
            "message": str(decision.get("message", "")).strip(),
            "question": question,
            "turn": len(qa_history) + 1,
        }
        suggested_answers = decision.get("suggested_answers")
        if suggested_answers:
            interrupt_payload["suggested_answers"] = suggested_answers
        answer = interrupt(interrupt_payload)
        updated_history = [
            *qa_history,
            {"question": question, "answer": str(answer).strip()},
        ]
        return Command(update={"qa_history": updated_history}, goto=node_name)

    draft = decision["draft"]
    return {
        "draft": draft,
        "response": formatter(
            draft,
            str(decision.get("message", "")).strip(),
            qa_history,
        ),
        "qa_history": qa_history,
    }


def _default_calendar_dir() -> str:
    return str(Path(__file__).resolve().parents[3] / "calendar")


def _load_long_term_items(path: Path) -> list[LongTermItem]:
    if not path.exists():
        return []
    return parse_long_term_items(path.read_text(encoding="utf-8"))


def _load_weekly_plan(path: Path) -> WeeklyPlan:
    if not path.exists():
        return default_weekly_plan()
    return parse_weekly_plan(path.read_text(encoding="utf-8"))


def _load_daily_plan(path: Path) -> DailyPlan:
    if not path.exists():
        return default_daily_plan()
    return parse_daily_plan(path.read_text(encoding="utf-8"))


def _load_week_daily_plans(calendar_dir: Path, week_start: str) -> dict[str, DailyPlan]:
    week_daily_plans: dict[str, DailyPlan] = {}
    for day in build_week_dates(week_start):
        week_daily_plans[day] = _load_daily_plan(calendar_dir / f"{day}.md")
    return week_daily_plans


def _build_local_checkpointer() -> InMemorySaver:
    return InMemorySaver(
        serde=JsonPlusSerializer(
            allowed_msgpack_modules=(
                ("agent.calendar_files", "DailyPlan"),
                ("agent.calendar_files", "LongTermItem"),
                ("agent.calendar_files", "WeeklyPlan"),
            )
        )
    )


def _compile_graph(*, checkpointer: InMemorySaver | None = None):
    builder = (
        StateGraph(State)
        .add_node("load_context", load_context)
        .add_node("weekly_plan", weekly_plan)
        .add_node("temp_plan", temp_plan)
        .add_node("daily_plan", daily_plan)
        .add_node("daily_reflect", daily_reflect)
        .add_node("weekly_reflect", weekly_reflect)
        .add_node("long_term_reflect", long_term_reflect)
        .add_edge(START, "load_context")
        .add_conditional_edges(
            "load_context",
            route_intent,
            {
                "weekly_plan": "weekly_plan",
                "temp_plan": "temp_plan",
                "daily_plan": "daily_plan",
                "daily_reflect": "daily_reflect",
                "weekly_reflect": "weekly_reflect",
                "long_term_reflect": "long_term_reflect",
            },
        )
        .add_edge("weekly_plan", END)
        .add_edge("temp_plan", END)
        .add_edge("daily_plan", END)
        .add_edge("daily_reflect", END)
        .add_edge("weekly_reflect", END)
        .add_edge("long_term_reflect", END)
    )

    compile_kwargs: dict[str, object] = {"name": "Calendar Planning Graph"}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    return builder.compile(**compile_kwargs)


# Local CLI/tests need an explicit checkpointer for interrupt/resume.
graph = _compile_graph(checkpointer=_build_local_checkpointer())

# LangGraph API manages persistence itself and rejects a custom checkpointer.
api_graph = _compile_graph()
