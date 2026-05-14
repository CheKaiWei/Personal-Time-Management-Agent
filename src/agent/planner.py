"""LLM-driven planning helpers and deterministic draft normalization."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
from typing import Any

from openai import AsyncOpenAI

from agent.calendar_files import DailyPlan, LongTermItem, WeeklyPlan, build_week_dates
from agent.config import OpenAISettings, build_openai_client, resolve_openai_settings

MAX_QA_TURNS = 3
MIN_WEEKLY_CHECKPOINTS = 5
MAX_WEEKLY_CHECKPOINTS = 7
MIN_DAILY_FOCUS_ITEMS = 2
PREFERRED_DAILY_FOCUS_ITEMS = 3
MAX_DAILY_FOCUS_ITEMS = 4
MAX_MEUS_PER_FOCUS = 3
DEFAULT_DAILY_TIME_SLOTS = (
    ("09:00", "10:30"),
    ("11:00", "12:00"),
    ("14:00", "15:30"),
    ("16:00", "17:00"),
)
PLANNER_SYSTEM_PROMPT = """
You are a careful calendar planning assistant.

You are helping a user maintain a local time-management system backed by markdown
files. You never write files directly. Your job is to think, ask clarifying
questions when needed, and produce planning drafts in JSON.

General rules:
- Work only from the provided context and prior Q&A.
- If a key decision is ambiguous, ask exactly one concise question.
- If enough information is available, do not ask a question. Finalize a draft.
- Once the clarification turn count reaches the configured limit, finalize using
  the best available judgment instead of asking more questions.
- Return JSON only, with no markdown fences and no extra prose.
- Keep all human-facing message/question text in Chinese.
""".strip()


async def plan_weekly_turn(
    *,
    current_date: str,
    week_start: str,
    long_term_items: list[LongTermItem],
    weekly_plan: WeeklyPlan,
    qa_history: list[dict[str, str]] | None,
    review_feedback_history: list[str] | None = None,
    previous_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Use the LLM to choose weekly checkpoints or ask a clarifying question."""
    fallback = build_weekly_plan_draft(
        current_date=current_date,
        week_start=week_start,
        long_term_items=long_term_items,
        weekly_plan=weekly_plan,
    )
    context = {
        "current_date": current_date,
        "week_start": week_start,
        "long_term_items": [_serialize_for_prompt(item) for item in long_term_items],
        "current_weekly_plan": _serialize_for_prompt(weekly_plan),
    }
    prompt = """
Workflow: weekly_plan
Goal: choose this week's 5-7 checkpoints from long-term items.

Rules:
- A checkpoint is a weekly outcome, not a micro-action.
- Prefer meaningful progress on important and urgent work, but do not blindly sort.
- When there are at least 5 active long-term items, do not return fewer than 5 checkpoints.
- Keep or mention relevant temp tasks only when they really matter this week.
- If review feedback exists, revise the previous draft to satisfy it unless it conflicts with the file context.
- If the current context is enough, finalize.
- If an important tradeoff is unclear, ask one concise question.

Return JSON with this shape:
{
  "status": "needs_input" | "ready",
  "message": "Chinese summary",
  "question": "Chinese question or empty string",
  "draft": {
    "weekly_checkpoints": [
      {
        "title": "string",
        "row_id": "string",
        "priority": "string",
        "urgency": "string",
        "expected_hours": "string",
        "reason": "Chinese rationale"
      }
    ],
    "temp_tasks": ["string"]
  }
}
""".strip()
    decision = await _request_llm_decision(
        workflow="weekly_plan",
        prompt=prompt,
        context=context,
        qa_history=qa_history or [],
        review_feedback_history=review_feedback_history or [],
        previous_draft=previous_draft,
    )
    return _normalize_weekly_decision(decision, fallback=fallback, long_term_items=long_term_items)


async def plan_temp_turn(
    *,
    weekly_plan: WeeklyPlan,
    qa_history: list[dict[str, str]] | None,
    review_feedback_history: list[str] | None = None,
    previous_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Use the LLM to structure temp tasks or ask a clarifying question."""
    fallback = build_temp_plan_draft(weekly_plan)
    context = {
        "weekly_plan": _serialize_for_prompt(weekly_plan),
    }
    prompt = """
Workflow: temp_plan
Goal: structure the raw Temp Tasks into useful categories and urgency levels.

Rules:
- Do not rely on keywords alone. Use task meaning.
- For each task, decide category, urgency, and whether it should enter this week.
- If review feedback exists, revise the previous draft to satisfy it unless it conflicts with the file context.
- If a task is too ambiguous to classify well, ask one concise question.
- If the current context is enough, finalize.

Return JSON with this shape:
{
  "status": "needs_input" | "ready",
  "message": "Chinese summary",
  "question": "Chinese question or empty string",
  "draft": {
    "structured_temp_tasks": [
      {
        "task": "string",
        "category": "admin | career | health | research | personal | general",
        "urgency": "high | medium | low",
        "should_enter_weekly_plan": true,
        "reason": "Chinese rationale"
      }
    ]
  }
}
""".strip()
    decision = await _request_llm_decision(
        workflow="temp_plan",
        prompt=prompt,
        context=context,
        qa_history=qa_history or [],
        review_feedback_history=review_feedback_history or [],
        previous_draft=previous_draft,
    )
    return _normalize_temp_decision(decision, fallback=fallback)


async def plan_daily_turn(
    *,
    current_date: str,
    weekly_plan: WeeklyPlan,
    daily_plan: DailyPlan,
    qa_history: list[dict[str, str]] | None,
    review_feedback_history: list[str] | None = None,
    previous_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Use the LLM to decompose weekly checkpoints into today's focus items."""
    fallback = build_daily_plan_draft(
        current_date=current_date,
        weekly_plan=weekly_plan,
        daily_plan=daily_plan,
    )
    context = {
        "current_date": current_date,
        "weekly_plan": _serialize_for_prompt(weekly_plan),
        "daily_plan": _serialize_for_prompt(daily_plan),
    }
    prompt = """
Workflow: daily_plan
Goal: turn this week's checkpoints into 2-4 realistic focus items for today.

Rules:
- If today's calendar already contains meaningful focus blocks, align with them unless
  there is a strong reason not to.
- Prefer work that clearly advances this week's checkpoints rather than unrelated filler.
- When enough weekly checkpoints exist, do not return fewer than 2 focus items.
- Each focus item must include 1-3 concrete and verifiable MEUs.
- Each focus item must include a time_block line that only names the checkpoint and includes start/end times.
- If review feedback exists, revise the previous draft to satisfy it unless it conflicts with the file context.
- Ask a concise clarifying question only if today's focus is genuinely ambiguous.

Return JSON with this shape:
{
  "status": "needs_input" | "ready",
  "message": "Chinese summary",
  "question": "Chinese question or empty string",
  "draft": {
    "focus_items": [
      {
        "checkpoint": "string",
        "reason": "Chinese rationale",
        "time_block": "- [ ] string [startTime:: HH:MM] [endTime:: HH:MM]",
        "meu_candidates": [
          {
            "action": "string",
            "expected_minutes": 30,
            "verification": "string"
          }
        ]
      }
    ]
  }
}
""".strip()
    decision = await _request_llm_decision(
        workflow="daily_plan",
        prompt=prompt,
        context=context,
        qa_history=qa_history or [],
        review_feedback_history=review_feedback_history or [],
        previous_draft=previous_draft,
    )
    return _normalize_daily_decision(decision, fallback=fallback)


async def plan_daily_reflect_turn(
    *,
    current_date: str,
    daily_plan: DailyPlan,
    qa_history: list[dict[str, str]] | None,
    review_feedback_history: list[str] | None = None,
    previous_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Use the LLM to ask reflection questions and summarize the day."""
    fallback = build_daily_reflect_draft(
        current_date=current_date,
        daily_plan=daily_plan,
    )
    context = {
        "current_date": current_date,
        "daily_plan": _serialize_for_prompt(daily_plan),
    }
    prompt = """
Workflow: daily_reflect
Goal: run a short daily reflection as multi-turn Q&A, then produce a concise summary.

Rules:
- If no prior user answer exists yet, you must first ask one concise question.
- Every question must include 3-5 candidate answers that the user can choose from or edit.
- You may ask follow-up questions to verify completion, blockers, and tomorrow's impact.
- When asking, ask only one concise question at a time.
- If review feedback exists, revise the previous draft to satisfy it unless it conflicts with the file context.
- Final reflection should focus on: completed work, incomplete work, deviation reasons,
  and tomorrow's next focus.

Return JSON with this shape:
{
  "status": "needs_input" | "ready",
  "message": "Chinese summary",
  "question": "Chinese question or empty string",
  "suggested_answers": ["string"],
  "draft": {
    "reflect_lines": [
      "- string",
      "- string"
    ]
  }
}
""".strip()
    decision = await _request_llm_decision(
        workflow="daily_reflect",
        prompt=prompt,
        context=context,
        qa_history=qa_history or [],
        review_feedback_history=review_feedback_history or [],
        previous_draft=previous_draft,
    )
    if not (qa_history or []) and decision.get("status") == "needs_input" and not decision.get("suggested_answers"):
        fallback_question = build_daily_reflect_question(
            current_date=current_date,
            daily_plan=daily_plan,
        )
        decision["suggested_answers"] = fallback_question["suggested_answers"]
    if not (qa_history or []) and decision.get("status") == "ready":
        return build_daily_reflect_question(
            current_date=current_date,
            daily_plan=daily_plan,
        )
    return _normalize_daily_reflect_decision(decision, fallback=fallback)


async def plan_weekly_reflect_turn(
    *,
    current_date: str,
    week_start: str,
    weekly_plan: WeeklyPlan,
    week_daily_plans: dict[str, DailyPlan],
    qa_history: list[dict[str, str]] | None,
    review_feedback_history: list[str] | None = None,
    previous_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Use the LLM to adjust the remaining schedule for this week."""
    fallback = build_weekly_reflect_draft(
        current_date=current_date,
        week_start=week_start,
        week_daily_plans=week_daily_plans,
    )
    context = {
        "current_date": current_date,
        "week_start": week_start,
        "weekly_plan": _serialize_for_prompt(weekly_plan),
        "executed_daily_plans": {
            day: _serialize_for_prompt(plan)
            for day, plan in week_daily_plans.items()
            if day <= current_date
        },
        "future_daily_plans": {
            day: _serialize_for_prompt(plan)
            for day, plan in week_daily_plans.items()
            if day > current_date
        },
    }
    prompt = """
Workflow: weekly_reflect
Goal: review this week's executed work so far and decide whether the remaining days need schedule adjustments.

Rules:
- Read only this week: today and earlier days are evidence; later days are adjustable targets.
- Do not modify past dates.
- If future days should change, produce updated Calendar blocks for those future dates only.
- Always produce at least one Adjustment Log line for the weekly plan file.
- If no future adjustment is needed, keep `future_daily_adjustments` empty and explain that in the log.
- If review feedback exists, revise the previous draft to satisfy it unless it conflicts with the file context.
- Ask a concise clarifying question only if a future-day constraint is genuinely unclear.

Return JSON with this shape:
{
  "status": "needs_input" | "ready",
  "message": "Chinese summary",
  "question": "Chinese question or empty string",
  "draft": {
    "adjustment_log_lines": [
      "- YYYY-MM-DD: string"
    ],
    "future_daily_adjustments": [
      {
        "date": "YYYY-MM-DD",
        "reason": "Chinese rationale",
        "calendar_blocks": [
          "- [ ] string [startTime:: HH:MM] [endTime:: HH:MM]"
        ]
      }
    ]
  }
}
""".strip()
    decision = await _request_llm_decision(
        workflow="weekly_reflect",
        prompt=prompt,
        context=context,
        qa_history=qa_history or [],
        review_feedback_history=review_feedback_history or [],
        previous_draft=previous_draft,
    )
    return _normalize_weekly_reflect_decision(
        decision,
        fallback=fallback,
        current_date=current_date,
        valid_week_dates=set(build_week_dates(week_start)),
    )


async def plan_long_term_reflect_turn(
    *,
    current_date: str,
    week_start: str,
    weekly_plan: WeeklyPlan,
    long_term_items: list[LongTermItem],
    qa_history: list[dict[str, str]] | None,
    review_feedback_history: list[str] | None = None,
    previous_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Use the LLM to revise only long-term urgency and notes."""
    fallback = build_long_term_reflect_draft(
        current_date=current_date,
        long_term_items=long_term_items,
    )
    context = {
        "current_date": current_date,
        "week_start": week_start,
        "weekly_plan": _serialize_for_prompt(weekly_plan),
        "long_term_items": [_serialize_for_prompt(item) for item in long_term_items],
    }
    prompt = """
Workflow: long_term_reflect
Goal: use the current date, deadline distance, and weekly-plan pressure to revise only the long-term E level and notes.

Rules:
- The only allowed write targets are `e_level` and `note_append`.
- Do not modify task names, project names, descriptions, status, P level, DDL, or hours.
- `note_append` must be concise, evidence-based, and suitable for appending to the Notes column.
- If nothing should change, return an empty `revisions` list.
- If review feedback exists, revise the previous draft to satisfy it unless it conflicts with the file context.
- Ask a concise clarifying question only if a high-stakes urgency tradeoff is genuinely unclear.

Return JSON with this shape:
{
  "status": "needs_input" | "ready",
  "message": "Chinese summary",
  "question": "Chinese question or empty string",
  "draft": {
    "revisions": [
      {
        "row_id": "string",
        "task": "string",
        "current_e_level": "string",
        "new_e_level": "string",
        "note_append": "string",
        "reason": "Chinese rationale"
      }
    ]
  }
}
""".strip()
    decision = await _request_llm_decision(
        workflow="long_term_reflect",
        prompt=prompt,
        context=context,
        qa_history=qa_history or [],
        review_feedback_history=review_feedback_history or [],
        previous_draft=previous_draft,
    )
    return _normalize_long_term_reflect_decision(
        decision,
        fallback=fallback,
        long_term_items=long_term_items,
    )


def format_weekly_plan_response(
    draft: dict[str, Any],
    llm_message: str = "",
    qa_history: list[dict[str, str]] | None = None,
) -> str:
    """Render a concise weekly plan preview."""
    lines: list[str] = []
    if llm_message:
        lines.append(f"LLM Summary: {llm_message}")

    checkpoints = draft["weekly_checkpoints"]
    checkpoint_lines = [
        (
            f"{index}. {item['title']} ({item['priority']}/{item['urgency']}, "
            f"{item['expected_hours']})"
            + (f" | reason: {item['reason']}" if item.get("reason") else "")
        )
        for index, item in enumerate(checkpoints, start=1)
    ] or ["1. No weekly checkpoint available."]
    temp_lines = [f"- {task}" for task in draft["temp_tasks"]] or ["- No temp tasks."]

    if qa_history:
        lines.append(f"Q&A turns: {len(qa_history)}")
    lines.extend(
        [
            f"Weekly plan draft for week start {draft['week_start']}:",
            "Weekly Checkpoint:",
            *checkpoint_lines,
            "Temp Tasks:",
            *temp_lines,
        ]
    )
    return "\n".join(lines)


def format_temp_plan_response(
    draft: dict[str, Any],
    llm_message: str = "",
    qa_history: list[dict[str, str]] | None = None,
) -> str:
    """Render a concise temp task preview."""
    tasks = draft["structured_temp_tasks"]
    lines: list[str] = []
    if llm_message:
        lines.append(f"LLM Summary: {llm_message}")
    if qa_history:
        lines.append(f"Q&A turns: {len(qa_history)}")
    if not tasks:
        lines.append("No Temp Tasks to structure.")
        return "\n".join(lines)

    for index, item in enumerate(tasks, start=1):
        enter_week = "yes" if item["should_enter_weekly_plan"] else "no"
        reason = f" | reason={item['reason']}" if item.get("reason") else ""
        lines.append(
            f"{index}. {item['task']} | category={item['category']} | "
            f"urgency={item['urgency']} | weekly={enter_week}{reason}"
        )
    return "\n".join(lines)


def format_daily_plan_response(
    draft: dict[str, Any],
    llm_message: str = "",
    qa_history: list[dict[str, str]] | None = None,
) -> str:
    """Render a concise daily plan preview."""
    focus_items = draft.get("focus_items") or _build_legacy_focus_items(draft)
    calendar_blocks = draft.get("calendar_blocks") or [
        focus["time_block"]
        for focus in focus_items
        if focus.get("time_block")
    ]
    lines: list[str] = []
    if llm_message:
        lines.append(f"LLM Summary: {llm_message}")
    if qa_history:
        lines.append(f"Q&A turns: {len(qa_history)}")
    lines.append(f"Daily plan draft for {draft['current_date']}:")
    lines.append("Today's focus items:")
    for index, focus in enumerate(focus_items, start=1):
        reason = f" | reason: {focus['reason']}" if focus.get("reason") else ""
        lines.append(f"{index}. {focus['checkpoint']}{reason}")
        lines.append(f"   block: {focus['time_block']}")
        lines.extend(
            (
                f"   {index}.{meu_index} {item['action']} | "
                f"verify: {item['verification']} | minutes={item['expected_minutes']}"
            )
            for meu_index, item in enumerate(focus["meu_candidates"], start=1)
        )
    lines.append("Calendar:")
    lines.extend(calendar_blocks)
    return "\n".join(lines)


def format_daily_reflect_response(
    draft: dict[str, Any],
    llm_message: str = "",
    qa_history: list[dict[str, str]] | None = None,
) -> str:
    """Render a concise daily reflection preview."""
    lines: list[str] = []
    if llm_message:
        lines.append(f"LLM Summary: {llm_message}")
    if qa_history:
        lines.append(f"Q&A turns: {len(qa_history)}")
    lines.append(f"Daily reflection draft for {draft['current_date']}:")
    lines.extend(draft["reflect_lines"])
    return "\n".join(lines)


def format_weekly_reflect_response(
    draft: dict[str, Any],
    llm_message: str = "",
    qa_history: list[dict[str, str]] | None = None,
) -> str:
    """Render a concise weekly reflection preview."""
    lines: list[str] = []
    if llm_message:
        lines.append(f"LLM Summary: {llm_message}")
    if qa_history:
        lines.append(f"Q&A turns: {len(qa_history)}")
    lines.append(f"Weekly reflection draft for {draft['current_date']}:")
    lines.append("Adjustment Log:")
    lines.extend(draft["adjustment_log_lines"] or ["- No weekly adjustment log generated."])
    if not draft["future_daily_adjustments"]:
        lines.append("Future daily adjustments: none")
        return "\n".join(lines)

    lines.append("Future daily adjustments:")
    for item in draft["future_daily_adjustments"]:
        reason = f" | reason: {item['reason']}" if item.get("reason") else ""
        lines.append(f"- {item['date']}{reason}")
        lines.extend(f"  {block}" for block in item["calendar_blocks"])
    return "\n".join(lines)


def format_long_term_reflect_response(
    draft: dict[str, Any],
    llm_message: str = "",
    qa_history: list[dict[str, str]] | None = None,
) -> str:
    """Render a concise long-term reflection preview."""
    lines: list[str] = []
    if llm_message:
        lines.append(f"LLM Summary: {llm_message}")
    if qa_history:
        lines.append(f"Q&A turns: {len(qa_history)}")
    lines.append(f"Long-term reflection draft for {draft['current_date']}:")
    if not draft["revisions"]:
        lines.append("No long-term revisions proposed.")
        return "\n".join(lines)

    for index, item in enumerate(draft["revisions"], start=1):
        note_text = f" | note: {item['note_append']}" if item.get("note_append") else ""
        reason = f" | reason: {item['reason']}" if item.get("reason") else ""
        lines.append(
            f"{index}. row={item['row_id']} | task={item['task']} | "
            f"E: {item['current_e_level']} -> {item['new_e_level']}{note_text}{reason}"
        )
    return "\n".join(lines)


def build_weekly_plan_draft(
    *,
    current_date: str,
    week_start: str,
    long_term_items: list[LongTermItem],
    weekly_plan: WeeklyPlan,
) -> dict[str, Any]:
    """Create a deterministic fallback weekly plan draft."""
    checkpoints = [
        {
            "title": _checkpoint_title(item),
            "row_id": item.row_id,
            "priority": item.p_level,
            "urgency": item.e_level,
            "expected_hours": item.expected_hours or "2h",
            "reason": "",
        }
        for item in _select_active_items(long_term_items, limit=MAX_WEEKLY_CHECKPOINTS)
    ]

    daily_links = [
        (date.fromisoformat(week_start) + timedelta(days=offset)).isoformat()
        for offset in range(7)
    ]

    return {
        "intent": "weekly_plan",
        "current_date": current_date,
        "week_start": week_start,
        "weekly_checkpoints": checkpoints,
        "temp_tasks": weekly_plan.temp_tasks,
        "daily_links": daily_links,
    }


def build_temp_plan_draft(weekly_plan: WeeklyPlan) -> dict[str, Any]:
    """Create a deterministic fallback temp plan draft."""
    structured_tasks = []
    for task in weekly_plan.temp_tasks:
        category = classify_temp_task(task)
        urgency = classify_temp_task_urgency(task)
        structured_tasks.append(
            {
                "task": task,
                "category": category,
                "urgency": urgency,
                "should_enter_weekly_plan": urgency == "high",
                "reason": "",
            }
        )

    return {
        "intent": "temp_plan",
        "structured_temp_tasks": structured_tasks,
    }


def build_daily_plan_draft(
    *,
    current_date: str,
    weekly_plan: WeeklyPlan,
    daily_plan: DailyPlan,
) -> dict[str, Any]:
    """Create a deterministic fallback daily plan draft."""
    candidate_checkpoints = _build_daily_checkpoint_candidates(
        weekly_plan=weekly_plan,
        daily_plan=daily_plan,
    )
    focus_count = _preferred_daily_focus_count(candidate_checkpoints)
    focus_items = [
        {
            "checkpoint": checkpoint,
            "reason": "",
            "time_block": _build_time_block(
                checkpoint,
                index=index,
                seed_line=daily_plan.calendar[index] if index < len(daily_plan.calendar) else None,
            ),
            "meu_candidates": build_meu_candidates(checkpoint),
        }
        for index, checkpoint in enumerate(candidate_checkpoints[:focus_count])
    ]
    if not focus_items:
        focus_items = [
            {
                "checkpoint": "Advance this week's checkpoints",
                "reason": "",
                "time_block": _build_time_block("Advance this week's checkpoints", index=0),
                "meu_candidates": build_meu_candidates("Advance this week's checkpoints"),
            }
        ]

    calendar_blocks = [item["time_block"] for item in focus_items]
    primary_focus = focus_items[0]

    return {
        "intent": "daily_plan",
        "current_date": current_date,
        "checkpoint": primary_focus["checkpoint"],
        "reason": primary_focus["reason"],
        "calendar_blocks": calendar_blocks,
        "meu_candidates": primary_focus["meu_candidates"],
        "focus_items": focus_items,
        "existing_notes": daily_plan.notes,
    }


def build_daily_reflect_draft(
    *,
    current_date: str,
    daily_plan: DailyPlan,
) -> dict[str, Any]:
    """Create a deterministic fallback daily reflection draft."""
    task_count = sum(1 for line in daily_plan.tasks if line.lstrip().startswith("- ["))
    completed_count = sum(1 for line in daily_plan.tasks if line.lstrip().startswith("- [x]"))
    pending_count = max(task_count - completed_count, 0)
    first_focus = _first_calendar_focus_text(daily_plan.calendar) or "today's main checkpoint"

    reflect_lines = [
        f"- Today had {len(daily_plan.calendar)} calendar blocks and {task_count} task lines.",
        f"- Completed {completed_count} task lines and left {pending_count} unfinished.",
        f"- Notes captured {len(daily_plan.notes)} evidence lines.",
        f"- Tomorrow should continue with: {first_focus}.",
    ]

    return {
        "intent": "daily_reflect",
        "current_date": current_date,
        "reflect_lines": reflect_lines,
    }


def build_daily_reflect_question(
    *,
    current_date: str,
    daily_plan: DailyPlan,
) -> dict[str, Any]:
    """Create a deterministic first-turn daily reflection question."""
    first_focus = _first_calendar_focus_text(daily_plan.calendar) or "today's main checkpoint"
    completed_count = sum(1 for line in daily_plan.tasks if line.lstrip().startswith("- [x]"))
    pending_count = sum(1 for line in daily_plan.tasks if line.lstrip().startswith("- [ ]"))
    note_count = len(daily_plan.notes)

    suggested_answers = [
        f"已基本完成，核心推进的是 {first_focus}。",
        f"部分完成，{first_focus} 还有收尾，当前大约完成一半到三分之二。",
        "执行明显偏离计划，主要被临时事项或中断打断。",
        "今天主要在补记录和澄清进度，实际完成情况还需要重新核对。",
    ]
    return {
        "status": "needs_input",
        "message": (
            f"今天记录里有 {completed_count} 条已完成任务、{pending_count} 条未完成任务，"
            f"以及 {note_count} 条笔记。先确认你的真实完成情况。"
        ),
        "question": "今天整体完成情况更接近下面哪一种？如果都不完全合适，也可以直接改写。",
        "suggested_answers": suggested_answers,
        "draft": {
            "intent": "daily_reflect",
            "current_date": current_date,
            "reflect_lines": [],
        },
    }


def build_weekly_reflect_draft(
    *,
    current_date: str,
    week_start: str,
    week_daily_plans: dict[str, DailyPlan],
) -> dict[str, Any]:
    """Create a deterministic fallback weekly reflection draft."""
    future_adjustments = [
        {
            "date": day,
            "reason": "",
            "calendar_blocks": plan.calendar,
        }
        for day, plan in sorted(week_daily_plans.items())
        if day > current_date and plan.calendar
    ]
    return {
        "intent": "weekly_reflect",
        "current_date": current_date,
        "week_start": week_start,
        "adjustment_log_lines": [
            f"- {current_date}: reviewed this week's execution and kept the remaining schedule unchanged."
        ],
        "future_daily_adjustments": future_adjustments,
    }


def build_long_term_reflect_draft(
    *,
    current_date: str,
    long_term_items: list[LongTermItem],
) -> dict[str, Any]:
    """Create a deterministic fallback long-term reflection draft."""
    revisions: list[dict[str, Any]] = []
    today = date.fromisoformat(current_date)

    for item in long_term_items:
        if not item.row_id or not item.task or not item.ddl or _is_done(item.status):
            continue
        try:
            ddl = date.fromisoformat(item.ddl)
        except ValueError:
            continue

        days_left = (ddl - today).days
        new_e_level = item.e_level or "E3"
        note_append = ""
        if days_left <= 3:
            new_e_level = "E1"
            note_append = f"距离 DDL 仅剩 {days_left} 天，需要优先推进。"
        elif days_left <= 7 and (item.e_level or "E9") != "E1":
            new_e_level = "E2"
            note_append = f"距离 DDL 仅剩 {days_left} 天，建议提高紧急度。"

        if new_e_level == (item.e_level or "") and not note_append:
            continue
        revisions.append(
            {
                "row_id": item.row_id,
                "task": _checkpoint_title(item),
                "current_e_level": item.e_level,
                "new_e_level": new_e_level,
                "note_append": note_append,
                "reason": "",
            }
        )

    return {
        "intent": "long_term_reflect",
        "current_date": current_date,
        "revisions": revisions,
    }


def build_meu_candidates(checkpoint: str) -> list[dict[str, Any]]:
    """Create deterministic fallback MEUs for a checkpoint."""
    focus = checkpoint.strip()
    return [
        {
            "action": f"Define the done condition for {focus}",
            "expected_minutes": 10,
            "verification": "Write one sentence describing today's completion bar.",
        },
        {
            "action": f"Push the core output of {focus} for 60 minutes",
            "expected_minutes": 60,
            "verification": "Produce a visible artifact or update record.",
        },
        {
            "action": f"Record blockers and the next step for {focus}",
            "expected_minutes": 10,
            "verification": "Add one progress note to Notes.",
        },
    ]


def _build_daily_checkpoint_candidates(
    *,
    weekly_plan: WeeklyPlan,
    daily_plan: DailyPlan,
) -> list[str]:
    existing_focuses = [
        focus
        for line in daily_plan.calendar
        if (focus := _extract_calendar_focus_text(line))
    ]
    weekly_focuses = [checkpoint.strip() for checkpoint in weekly_plan.checkpoints if checkpoint.strip()]
    candidate_checkpoints = _unique_non_empty([*existing_focuses, *weekly_focuses])
    if candidate_checkpoints:
        return candidate_checkpoints
    return ["Advance this week's checkpoints"]


def _preferred_daily_focus_count(candidate_checkpoints: list[str]) -> int:
    if not candidate_checkpoints:
        return 1
    if len(candidate_checkpoints) >= PREFERRED_DAILY_FOCUS_ITEMS:
        return min(PREFERRED_DAILY_FOCUS_ITEMS, MAX_DAILY_FOCUS_ITEMS)
    if len(candidate_checkpoints) >= MIN_DAILY_FOCUS_ITEMS:
        return len(candidate_checkpoints)
    return 1


def _build_time_block(
    checkpoint: str,
    *,
    index: int,
    seed_line: str | None = None,
) -> str:
    start_time, end_time = _extract_time_window(seed_line) or DEFAULT_DAILY_TIME_SLOTS[
        index % len(DEFAULT_DAILY_TIME_SLOTS)
    ]
    return f"- [ ] {checkpoint} [startTime:: {start_time}] [endTime:: {end_time}]"


def classify_temp_task(task: str) -> str:
    """Assign a deterministic fallback category to a temp task."""
    category_rules = {
        "admin": ("签证", "visa", "护照", "报销", "发票", "手续"),
        "career": ("面试", "简历", "投递", "offer"),
        "health": ("健身", "医院", "体检", "跑步"),
        "research": ("paper", "论文", "实验", "camera ready"),
    }

    lowered_task = task.lower()
    for category, keywords in category_rules.items():
        if any(keyword.lower() in lowered_task for keyword in keywords):
            return category
    return "general"


def classify_temp_task_urgency(task: str) -> str:
    """Assign a deterministic fallback urgency score to a temp task."""
    high_keywords = ("签证", "visa", "面试", "ddl", "截止", "camera ready")
    medium_keywords = ("报销", "简历", "健身", "实验")
    lowered_task = task.lower()

    if any(keyword.lower() in lowered_task for keyword in high_keywords):
        return "high"
    if any(keyword.lower() in lowered_task for keyword in medium_keywords):
        return "medium"
    return "low"


async def _request_llm_decision(
    *,
    workflow: str,
    prompt: str,
    context: dict[str, Any],
    qa_history: list[dict[str, str]],
    review_feedback_history: list[str],
    previous_draft: dict[str, Any] | None,
    client: AsyncOpenAI | None = None,
) -> dict[str, Any]:
    settings = resolve_openai_settings(system_prompt=PLANNER_SYSTEM_PROMPT)
    content = "\n\n".join(
        [
            prompt,
            f"Clarification turns used: {len(qa_history)} / {MAX_QA_TURNS}",
            "Prior Q&A:",
            _format_qa_history(qa_history),
            "Review feedback history:",
            _format_review_feedback_history(review_feedback_history),
            "Previous draft JSON:",
            json.dumps(previous_draft or {}, ensure_ascii=False, indent=2),
            "Context JSON:",
            json.dumps(context, ensure_ascii=False, indent=2),
        ]
    )

    if client is None:
        async with build_openai_client(settings) as local_client:
            return await _create_llm_decision(
                client=local_client,
                settings=settings,
                workflow=workflow,
                content=content,
            )

    return await _create_llm_decision(
        client=client,
        settings=settings,
        workflow=workflow,
        content=content,
    )


async def _create_llm_decision(
    *,
    client: AsyncOpenAI,
    settings: OpenAISettings,
    workflow: str,
    content: str,
) -> dict[str, Any]:
    response = await client.responses.create(
        model=settings.model,
        instructions=settings.system_prompt,
        input=content,
    )
    output_text = (response.output_text or "").strip()
    if not output_text:
        raise RuntimeError(f"OpenAI returned an empty response for {workflow}.")

    payload = _extract_json_payload(output_text)
    if not isinstance(payload, dict):
        raise RuntimeError(f"OpenAI returned non-object JSON for {workflow}.")
    return payload


def _normalize_weekly_decision(
    decision: dict[str, Any],
    *,
    fallback: dict[str, Any],
    long_term_items: list[LongTermItem],
) -> dict[str, Any]:
    if decision.get("status") != "ready":
        return _normalize_question_decision(decision)

    row_lookup = {item.row_id: item for item in long_term_items}
    raw_draft = decision.get("draft") or {}
    raw_items = raw_draft.get("weekly_checkpoints") or []
    weekly_checkpoints: list[dict[str, Any]] = []

    for raw_item in raw_items[:MAX_WEEKLY_CHECKPOINTS]:
        if not isinstance(raw_item, dict):
            continue
        title = str(raw_item.get("title", "")).strip()
        if not title:
            continue
        row_id = str(raw_item.get("row_id", "")).strip()
        source_item = row_lookup.get(row_id)
        weekly_checkpoints.append(
            {
                "title": title,
                "row_id": row_id,
                "priority": str(raw_item.get("priority") or (source_item.p_level if source_item else "")).strip(),
                "urgency": str(raw_item.get("urgency") or (source_item.e_level if source_item else "")).strip(),
                "expected_hours": str(
                    raw_item.get("expected_hours")
                    or (source_item.expected_hours if source_item else "")
                    or "2h"
                ).strip(),
                "reason": str(raw_item.get("reason", "")).strip(),
            }
        )

    weekly_checkpoints = _merge_weekly_checkpoints(
        primary=weekly_checkpoints,
        fallback=fallback["weekly_checkpoints"],
        minimum_count=min(MIN_WEEKLY_CHECKPOINTS, len(fallback["weekly_checkpoints"])),
    )

    temp_tasks = raw_draft.get("temp_tasks")
    if not isinstance(temp_tasks, list) or not temp_tasks:
        temp_tasks = fallback["temp_tasks"]

    return {
        "status": "ready",
        "message": str(decision.get("message", "")).strip(),
        "draft": {
            **fallback,
            "weekly_checkpoints": weekly_checkpoints[:MAX_WEEKLY_CHECKPOINTS],
            "temp_tasks": [str(task).strip() for task in temp_tasks if str(task).strip()],
        },
    }


def _normalize_temp_decision(
    decision: dict[str, Any],
    *,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if decision.get("status") != "ready":
        return _normalize_question_decision(decision)

    raw_draft = decision.get("draft") or {}
    raw_items = raw_draft.get("structured_temp_tasks") or []
    structured_temp_tasks: list[dict[str, Any]] = []

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        task = str(raw_item.get("task", "")).strip()
        if not task:
            continue
        urgency = str(raw_item.get("urgency", "")).strip().lower()
        if urgency not in {"high", "medium", "low"}:
            urgency = classify_temp_task_urgency(task)
        structured_temp_tasks.append(
            {
                "task": task,
                "category": str(raw_item.get("category") or classify_temp_task(task)).strip(),
                "urgency": urgency,
                "should_enter_weekly_plan": bool(raw_item.get("should_enter_weekly_plan")),
                "reason": str(raw_item.get("reason", "")).strip(),
            }
        )

    if not structured_temp_tasks:
        structured_temp_tasks = fallback["structured_temp_tasks"]

    return {
        "status": "ready",
        "message": str(decision.get("message", "")).strip(),
        "draft": {
            "intent": "temp_plan",
            "structured_temp_tasks": structured_temp_tasks,
        },
    }


def _normalize_daily_decision(
    decision: dict[str, Any],
    *,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if decision.get("status") != "ready":
        return _normalize_question_decision(decision)

    raw_draft = decision.get("draft") or {}
    raw_focus_items = raw_draft.get("focus_items") or []
    if not raw_focus_items and raw_draft.get("checkpoint"):
        raw_focus_items = [raw_draft]

    focus_items: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_focus_items[:MAX_DAILY_FOCUS_ITEMS]):
        if not isinstance(raw_item, dict):
            continue
        checkpoint = str(raw_item.get("checkpoint", "")).strip()
        if not checkpoint:
            continue
        fallback_focus = fallback["focus_items"][index] if index < len(fallback["focus_items"]) else None
        focus_items.append(
            {
                "checkpoint": checkpoint,
                "reason": str(raw_item.get("reason", "")).strip(),
                "time_block": _normalize_time_block(
                    raw_item.get("time_block"),
                    checkpoint=checkpoint,
                    index=index,
                    fallback_time_block=fallback_focus["time_block"] if fallback_focus else None,
                ),
                "meu_candidates": _normalize_meu_candidates(
                    raw_item.get("meu_candidates"),
                    fallback_focus["meu_candidates"] if fallback_focus else build_meu_candidates(checkpoint),
                ),
            }
        )

    focus_items = _merge_daily_focus_items(
        primary=focus_items,
        fallback=fallback["focus_items"],
        minimum_count=min(MIN_DAILY_FOCUS_ITEMS, len(fallback["focus_items"])),
    )
    primary_focus = focus_items[0]

    return {
        "status": "ready",
        "message": str(decision.get("message", "")).strip(),
        "draft": {
            **fallback,
            "checkpoint": primary_focus["checkpoint"],
            "reason": primary_focus["reason"],
            "meu_candidates": primary_focus["meu_candidates"],
            "focus_items": focus_items,
            "calendar_blocks": [item["time_block"] for item in focus_items],
        },
    }


def _normalize_daily_reflect_decision(
    decision: dict[str, Any],
    *,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    if decision.get("status") != "ready":
        return _normalize_question_decision(decision)

    raw_draft = decision.get("draft") or {}
    raw_lines = raw_draft.get("reflect_lines") or []
    reflect_lines = [_normalize_reflect_line(line) for line in raw_lines if str(line).strip()]
    if not reflect_lines:
        reflect_lines = fallback["reflect_lines"]

    return {
        "status": "ready",
        "message": str(decision.get("message", "")).strip(),
        "draft": {
            **fallback,
            "reflect_lines": reflect_lines,
        },
    }


def _normalize_weekly_reflect_decision(
    decision: dict[str, Any],
    *,
    fallback: dict[str, Any],
    current_date: str,
    valid_week_dates: set[str],
) -> dict[str, Any]:
    if decision.get("status") != "ready":
        return _normalize_question_decision(decision)

    raw_draft = decision.get("draft") or {}
    raw_logs = raw_draft.get("adjustment_log_lines") or []
    adjustment_log_lines = [
        _normalize_reflect_line(line)
        for line in raw_logs
        if str(line).strip()
    ]
    if not adjustment_log_lines:
        adjustment_log_lines = fallback["adjustment_log_lines"]

    future_daily_adjustments: list[dict[str, Any]] = []
    for raw_item in raw_draft.get("future_daily_adjustments") or []:
        if not isinstance(raw_item, dict):
            continue
        target_date = str(raw_item.get("date", "")).strip()
        if not target_date or target_date not in valid_week_dates or target_date <= current_date:
            continue
        calendar_blocks = [
            str(block).strip()
            for block in (raw_item.get("calendar_blocks") or [])
            if str(block).strip()
        ]
        future_daily_adjustments.append(
            {
                "date": target_date,
                "reason": str(raw_item.get("reason", "")).strip(),
                "calendar_blocks": calendar_blocks,
            }
        )

    if not future_daily_adjustments:
        future_daily_adjustments = fallback["future_daily_adjustments"]

    return {
        "status": "ready",
        "message": str(decision.get("message", "")).strip(),
        "draft": {
            **fallback,
            "adjustment_log_lines": adjustment_log_lines,
            "future_daily_adjustments": future_daily_adjustments,
        },
    }


def _normalize_long_term_reflect_decision(
    decision: dict[str, Any],
    *,
    fallback: dict[str, Any],
    long_term_items: list[LongTermItem],
) -> dict[str, Any]:
    if decision.get("status") != "ready":
        return _normalize_question_decision(decision)

    row_lookup = {item.row_id: item for item in long_term_items}
    revisions: list[dict[str, Any]] = []
    for raw_item in (decision.get("draft") or {}).get("revisions") or []:
        if not isinstance(raw_item, dict):
            continue
        row_id = str(raw_item.get("row_id", "")).strip()
        source_item = row_lookup.get(row_id)
        if source_item is None:
            continue
        new_e_level = str(raw_item.get("new_e_level") or source_item.e_level).strip().upper()
        if not re.fullmatch(r"E\d+", new_e_level):
            new_e_level = source_item.e_level
        note_append = str(raw_item.get("note_append", "")).strip()
        if new_e_level == source_item.e_level and not note_append:
            continue
        revisions.append(
            {
                "row_id": row_id,
                "task": str(raw_item.get("task") or _checkpoint_title(source_item)).strip(),
                "current_e_level": source_item.e_level,
                "new_e_level": new_e_level,
                "note_append": note_append,
                "reason": str(raw_item.get("reason", "")).strip(),
            }
        )

    if not revisions:
        revisions = fallback["revisions"]

    return {
        "status": "ready",
        "message": str(decision.get("message", "")).strip(),
        "draft": {
            **fallback,
            "revisions": revisions,
        },
    }


def _normalize_question_decision(decision: dict[str, Any]) -> dict[str, Any]:
    question = str(decision.get("question", "")).strip()
    if not question:
        raise RuntimeError("LLM requested more input but did not provide a question.")
    suggested_answers = _normalize_suggested_answers(decision.get("suggested_answers"))
    return {
        "status": "needs_input",
        "message": str(decision.get("message", "")).strip(),
        "question": question,
        "suggested_answers": suggested_answers,
    }


def _format_qa_history(qa_history: list[dict[str, str]]) -> str:
    if not qa_history:
        return "None"
    lines = []
    for index, item in enumerate(qa_history, start=1):
        lines.append(f"Q{index}: {item['question']}")
        lines.append(f"A{index}: {item['answer']}")
    return "\n".join(lines)


def _format_review_feedback_history(review_feedback_history: list[str]) -> str:
    if not review_feedback_history:
        return "None"
    return "\n".join(
        f"Feedback {index}: {feedback}"
        for index, feedback in enumerate(review_feedback_history, start=1)
    )


def _extract_json_payload(text: str) -> dict[str, Any]:
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence_match:
        return json.loads(fence_match.group(1))

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise RuntimeError("OpenAI response did not include a JSON object.")
    return json.loads(text[start : end + 1])


def _serialize_for_prompt(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _serialize_for_prompt(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [_serialize_for_prompt(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_for_prompt(item) for key, item in value.items()}
    return value


def _normalize_reflect_line(line: Any) -> str:
    text = str(line).strip()
    if not text:
        return text
    return text if text.startswith("- ") else f"- {text.lstrip('- ').strip()}"


def _normalize_suggested_answers(raw_answers: Any) -> list[str]:
    answers: list[str] = []
    for raw_item in raw_answers or []:
        text = str(raw_item).strip()
        if not text or text in answers:
            continue
        answers.append(text)
        if len(answers) >= 5:
            break
    return answers


def _normalize_meu_candidates(
    raw_meus: Any,
    fallback_meus: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    meu_candidates: list[dict[str, Any]] = []
    for raw_item in (raw_meus or [])[:MAX_MEUS_PER_FOCUS]:
        if not isinstance(raw_item, dict):
            continue
        action = str(raw_item.get("action", "")).strip()
        verification = str(raw_item.get("verification", "")).strip()
        if not action or not verification:
            continue
        expected_minutes = raw_item.get("expected_minutes")
        try:
            expected_minutes = int(expected_minutes)
        except (TypeError, ValueError):
            expected_minutes = 30
        meu_candidates.append(
            {
                "action": action,
                "expected_minutes": expected_minutes,
                "verification": verification,
            }
        )

    return meu_candidates or fallback_meus[:MAX_MEUS_PER_FOCUS]


def _merge_weekly_checkpoints(
    *,
    primary: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
    minimum_count: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in [*primary, *fallback]:
        key = str(item.get("row_id") or item.get("title") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= MAX_WEEKLY_CHECKPOINTS:
            break

    if len(merged) >= minimum_count:
        return merged
    return merged or fallback[:MAX_WEEKLY_CHECKPOINTS]


def _merge_daily_focus_items(
    *,
    primary: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
    minimum_count: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in [*primary, *fallback]:
        checkpoint = str(item.get("checkpoint", "")).strip()
        if not checkpoint or checkpoint in seen:
            continue
        seen.add(checkpoint)
        merged.append(item)
        if len(merged) >= MAX_DAILY_FOCUS_ITEMS:
            break

    if len(merged) >= minimum_count:
        return merged
    return merged or fallback[:MAX_DAILY_FOCUS_ITEMS]


def _normalize_time_block(
    raw_time_block: Any,
    *,
    checkpoint: str,
    index: int,
    fallback_time_block: str | None = None,
) -> str:
    time_block = str(raw_time_block or "").strip()
    if time_block:
        return _build_time_block(checkpoint, index=index, seed_line=time_block)
    if fallback_time_block:
        return _build_time_block(checkpoint, index=index, seed_line=fallback_time_block)
    return _build_time_block(checkpoint, index=index)


def _build_legacy_focus_items(draft: dict[str, Any]) -> list[dict[str, Any]]:
    checkpoint = str(draft.get("checkpoint", "")).strip()
    if not checkpoint:
        return []
    return [
        {
            "checkpoint": checkpoint,
            "reason": str(draft.get("reason", "")).strip(),
            "time_block": (
                draft.get("calendar_blocks", ["- [ ] " + checkpoint])[0]
                if draft.get("calendar_blocks")
                else _build_time_block(checkpoint, index=0)
            ),
            "meu_candidates": draft.get("meu_candidates", []),
        }
    ]


def _select_active_items(long_term_items: list[LongTermItem], limit: int) -> list[LongTermItem]:
    active_items = [item for item in long_term_items if item.task and not _is_done(item.status)]
    return sorted(active_items, key=_priority_sort_key)[:limit]


def _priority_sort_key(item: LongTermItem) -> tuple[int, int, str, str]:
    return (
        _level_value(item.p_level),
        _level_value(item.e_level),
        item.ddl or "9999-12-31",
        item.task,
    )


def _level_value(value: str) -> int:
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else 99


def _is_done(status: str) -> bool:
    lowered_status = status.lower()
    return lowered_status in {"done", "finish", "finished", "complete", "completed"}


def _checkpoint_title(item: LongTermItem) -> str:
    if item.project:
        return f"{item.project} / {item.task}"
    return item.task


def _extract_calendar_focus_text(line: str) -> str | None:
    text = line.strip()
    if not text:
        return None
    text = re.sub(r"^\s*-\s*", "", text)
    text = re.sub(r"^\[[ xX]\]\s*", "", text)
    text = re.sub(r"\s*\[startTime:: [^\]]+\]", "", text)
    text = re.sub(r"\s*\[endTime:: [^\]]+\]", "", text)
    cleaned = text.strip()
    return cleaned or None


def _first_calendar_focus_text(lines: list[str]) -> str | None:
    for line in lines:
        if focus := _extract_calendar_focus_text(line):
            return focus
    return None


def _extract_time_window(line: str | None) -> tuple[str, str] | None:
    if not line:
        return None
    start_match = re.search(r"\[startTime:: (?P<time>[^\]]+)\]", line)
    end_match = re.search(r"\[endTime:: (?P<time>[^\]]+)\]", line)
    if not start_match or not end_match:
        return None
    return start_match.group("time").strip(), end_match.group("time").strip()


def _unique_non_empty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_values.append(normalized)
    return unique_values
