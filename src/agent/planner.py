"""LLM-driven planning helpers and deterministic draft normalization."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
from typing import Any

from openai import AsyncOpenAI

from agent.calendar_files import DailyPlan, LongTermItem, WeeklyPlan
from agent.config import OpenAISettings, build_openai_client, resolve_openai_settings

MAX_QA_TURNS = 3
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
Goal: choose this week's 3-5 checkpoints from long-term items.

Rules:
- A checkpoint is a weekly outcome, not a micro-action.
- Prefer meaningful progress on important and urgent work, but do not blindly sort.
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
    """Use the LLM to choose today's checkpoint and MEUs."""
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
Goal: choose exactly one checkpoint for today and break it into 1-3 MEUs.

Rules:
- Choose exactly one checkpoint.
- If today's calendar already contains meaningful focus blocks, align with them unless
  there is a strong reason not to.
- Each MEU must be concrete and verifiable.
- If review feedback exists, revise the previous draft to satisfy it unless it conflicts with the file context.
- Ask a concise clarifying question only if today's focus is genuinely ambiguous.

Return JSON with this shape:
{
  "status": "needs_input" | "ready",
  "message": "Chinese summary",
  "question": "Chinese question or empty string",
  "draft": {
    "checkpoint": "string",
    "reason": "Chinese rationale",
    "meu_candidates": [
      {
        "action": "string",
        "expected_minutes": 30,
        "verification": "string"
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
- You may ask follow-up questions to verify completion, blockers, and tomorrow's impact.
- If the existing evidence is already enough, you may finalize immediately.
- When asking, ask only one concise question at a time.
- If review feedback exists, revise the previous draft to satisfy it unless it conflicts with the file context.
- Final reflection should focus on: completed work, incomplete work, deviation reasons,
  and tomorrow's next focus.

Return JSON with this shape:
{
  "status": "needs_input" | "ready",
  "message": "Chinese summary",
  "question": "Chinese question or empty string",
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
    return _normalize_daily_reflect_decision(decision, fallback=fallback)


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
    lines: list[str] = []
    if llm_message:
        lines.append(f"LLM Summary: {llm_message}")
    if qa_history:
        lines.append(f"Q&A turns: {len(qa_history)}")
    if draft.get("reason"):
        lines.append(f"Checkpoint reason: {draft['reason']}")
    lines.extend(
        [
            f"Daily plan draft for {draft['current_date']}:",
            f"Today's checkpoint: {draft['checkpoint']}",
            "MEU:",
        ]
    )
    lines.extend(
        (
            f"{index}. {item['action']} | verify: {item['verification']} | "
            f"minutes={item['expected_minutes']}"
        )
        for index, item in enumerate(draft["meu_candidates"], start=1)
    )
    lines.append("Calendar:")
    lines.extend(draft["calendar_blocks"])
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
        for item in _select_active_items(long_term_items, limit=5)
    ]
    if len(checkpoints) > 3:
        checkpoints = checkpoints[:3]

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
    checkpoint = _first_checkbox_text(daily_plan.calendar)
    if not checkpoint:
        checkpoint = (
            weekly_plan.checkpoints[0]
            if weekly_plan.checkpoints
            else "Add today's single checkpoint"
        )
    calendar_blocks = daily_plan.calendar or [
        f"- [ ] {checkpoint} [startTime:: 09:00] [endTime:: 10:30]",
        f"- [ ] {checkpoint} [startTime:: 14:00] [endTime:: 15:00]",
    ]
    meu_candidates = build_meu_candidates(checkpoint)

    return {
        "intent": "daily_plan",
        "current_date": current_date,
        "checkpoint": checkpoint,
        "reason": "",
        "calendar_blocks": calendar_blocks,
        "meu_candidates": meu_candidates,
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
    first_focus = _first_checkbox_text(daily_plan.calendar) or "today's main checkpoint"

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

    for raw_item in raw_items[:5]:
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

    if not weekly_checkpoints:
        weekly_checkpoints = fallback["weekly_checkpoints"]

    temp_tasks = raw_draft.get("temp_tasks")
    if not isinstance(temp_tasks, list) or not temp_tasks:
        temp_tasks = fallback["temp_tasks"]

    return {
        "status": "ready",
        "message": str(decision.get("message", "")).strip(),
        "draft": {
            **fallback,
            "weekly_checkpoints": weekly_checkpoints[:5],
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
    checkpoint = str(raw_draft.get("checkpoint") or fallback["checkpoint"]).strip()
    reason = str(raw_draft.get("reason", "")).strip()
    raw_meus = raw_draft.get("meu_candidates") or []
    meu_candidates: list[dict[str, Any]] = []

    for raw_item in raw_meus[:3]:
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

    if not meu_candidates:
        meu_candidates = fallback["meu_candidates"]

    return {
        "status": "ready",
        "message": str(decision.get("message", "")).strip(),
        "draft": {
            **fallback,
            "checkpoint": checkpoint or fallback["checkpoint"],
            "reason": reason,
            "meu_candidates": meu_candidates[:3],
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


def _normalize_question_decision(decision: dict[str, Any]) -> dict[str, Any]:
    question = str(decision.get("question", "")).strip()
    if not question:
        raise RuntimeError("LLM requested more input but did not provide a question.")
    return {
        "status": "needs_input",
        "message": str(decision.get("message", "")).strip(),
        "question": question,
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


def _first_checkbox_text(lines: list[str]) -> str | None:
    for line in lines:
        match = re.match(r"^\s*-\s*\[[ xX]\]\s*(?P<item>.+?)\s*$", line)
        if match:
            item = match.group("item")
            item = re.sub(r"\s*\[startTime:: [^\]]+\]", "", item)
            item = re.sub(r"\s*\[endTime:: [^\]]+\]", "", item)
            return item.strip()
    return None
