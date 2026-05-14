"""Deterministic planning helpers used by the LangGraph nodes."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from agent.calendar_files import DailyPlan, LongTermItem, WeeklyPlan


def build_weekly_plan_draft(
    *,
    current_date: str,
    week_start: str,
    long_term_items: list[LongTermItem],
    weekly_plan: WeeklyPlan,
) -> dict[str, Any]:
    """Create a minimal weekly plan draft from the current files."""
    checkpoints = [
        {
            "title": _checkpoint_title(item),
            "row_id": item.row_id,
            "priority": item.p_level,
            "urgency": item.e_level,
            "expected_hours": item.expected_hours or "2h",
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


def format_weekly_plan_response(draft: dict[str, Any]) -> str:
    """Render a concise weekly plan preview."""
    checkpoints = draft["weekly_checkpoints"]
    checkpoint_lines = [
        f"{index}. {item['title']} ({item['priority']}/{item['urgency']}, {item['expected_hours']})"
        for index, item in enumerate(checkpoints, start=1)
    ] or ["1. 本周暂无可推进 checkpoint，请先补长期目标。"]
    temp_lines = [f"- {task}" for task in draft["temp_tasks"]] or ["- 本周暂无临时任务。"]

    return "\n".join(
        [
            f"已生成本周计划草案（未写入）。周起始：{draft['week_start']}",
            "Weekly Checkpoint:",
            *checkpoint_lines,
            "Temp Tasks:",
            *temp_lines,
        ]
    )


def build_temp_plan_draft(weekly_plan: WeeklyPlan) -> dict[str, Any]:
    """Structure raw temp tasks into a stable preview."""
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
            }
        )

    return {
        "intent": "temp_plan",
        "structured_temp_tasks": structured_tasks,
    }


def format_temp_plan_response(draft: dict[str, Any]) -> str:
    """Render a concise temp task preview."""
    tasks = draft["structured_temp_tasks"]
    if not tasks:
        return "已生成临时任务草案（未写入）。当前没有待整理的 Temp Tasks。"

    lines = ["已生成临时任务草案（未写入）。"]
    for index, item in enumerate(tasks, start=1):
        enter_week = "yes" if item["should_enter_weekly_plan"] else "no"
        lines.append(
            f"{index}. {item['task']} | category={item['category']} | urgency={item['urgency']} | weekly={enter_week}"
        )
    return "\n".join(lines)


def build_daily_plan_draft(
    *,
    current_date: str,
    weekly_plan: WeeklyPlan,
    daily_plan: DailyPlan,
) -> dict[str, Any]:
    """Create a daily plan draft from weekly goals and today's file."""
    checkpoint = _first_checkbox_text(daily_plan.calendar)
    if not checkpoint:
        checkpoint = (
            weekly_plan.checkpoints[0]
            if weekly_plan.checkpoints
            else "补充今天的唯一 checkpoint"
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
        "calendar_blocks": calendar_blocks,
        "meu_candidates": meu_candidates,
        "existing_notes": daily_plan.notes,
    }


def format_daily_plan_response(draft: dict[str, Any]) -> str:
    """Render a concise daily plan preview."""
    lines = [
        f"已生成日计划草案（未写入）。日期：{draft['current_date']}",
        f"今日 checkpoint：{draft['checkpoint']}",
        "MEU:",
    ]
    lines.extend(
        f"{index}. {item['action']}；验证：{item['verification']}"
        for index, item in enumerate(draft["meu_candidates"], start=1)
    )
    lines.append("Calendar:")
    lines.extend(draft["calendar_blocks"])
    return "\n".join(lines)


def build_daily_reflect_draft(
    *,
    current_date: str,
    daily_plan: DailyPlan,
) -> dict[str, Any]:
    """Create a daily reflection draft from the current day file."""
    task_count = sum(1 for line in daily_plan.tasks if line.lstrip().startswith("- ["))
    completed_count = sum(1 for line in daily_plan.tasks if line.lstrip().startswith("- [x]"))
    pending_count = max(task_count - completed_count, 0)
    first_focus = _first_checkbox_text(daily_plan.calendar) or "今天的核心 checkpoint"

    reflect_lines = [
        f"- 今天共安排 {len(daily_plan.calendar)} 个时间块，记录 {task_count} 条任务。",
        f"- 已完成 {completed_count} 条，未完成 {pending_count} 条。",
        f"- 备注区共有 {len(daily_plan.notes)} 条记录。",
        f"- 明天优先延续：{first_focus}。",
    ]

    return {
        "intent": "daily_reflect",
        "current_date": current_date,
        "reflect_lines": reflect_lines,
    }


def format_daily_reflect_response(draft: dict[str, Any]) -> str:
    """Render a concise daily reflection preview."""
    return "\n".join(
        [f"已生成日复盘草案（未写入）。日期：{draft['current_date']}", *draft["reflect_lines"]]
    )


def build_meu_candidates(checkpoint: str) -> list[dict[str, Any]]:
    """Create 1-3 verifiable MEU candidates from a checkpoint title."""
    focus = checkpoint.strip()
    return [
        {
            "action": f"明确 {focus} 的完成定义",
            "expected_minutes": 10,
            "verification": "写下一句今天完成标准。",
        },
        {
            "action": f"推进 {focus} 的核心产出 60 分钟",
            "expected_minutes": 60,
            "verification": "产出一段可见成果或更新记录。",
        },
        {
            "action": f"记录 {focus} 的阻塞和下一步",
            "expected_minutes": 10,
            "verification": "在 Notes 中补 1 条进展记录。",
        },
    ]


def classify_temp_task(task: str) -> str:
    """Assign a coarse category to a temp task."""
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
    """Assign a simple urgency score to a temp task."""
    high_keywords = ("签证", "visa", "面试", "ddl", "截止", "camera ready")
    medium_keywords = ("报销", "简历", "健身", "实验")
    lowered_task = task.lower()

    if any(keyword.lower() in lowered_task for keyword in high_keywords):
        return "high"
    if any(keyword.lower() in lowered_task for keyword in medium_keywords):
        return "medium"
    return "low"


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
