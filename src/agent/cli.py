"""Terminal entrypoint for the calendar planning workflows."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

from agent.calendar_writes import (
    FilePatch,
    apply_file_patches,
    build_daily_plan_patches,
    build_daily_reflect_patches,
    build_temp_plan_patches,
    build_weekly_plan_patches,
)
from agent.graph import Intent, graph

MENU_OPTIONS: dict[str, tuple[str, Intent]] = {
    "1": ("Weekly Plan", "weekly_plan"),
    "2": ("Temp Plan", "temp_plan"),
    "3": ("Daily Plan", "daily_plan"),
    "4": ("Daily Reflect", "daily_reflect"),
}


def build_parser() -> argparse.ArgumentParser:
    """Create a CLI parser for interactive and scripted workflow usage."""
    parser = argparse.ArgumentParser(description="Run the calendar planning workflows.")
    parser.add_argument(
        "--intent",
        choices=[option[1] for option in MENU_OPTIONS.values()],
        help="Run a single workflow without showing the menu.",
    )
    parser.add_argument(
        "--date",
        dest="current_date",
        help="Target date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--calendar-dir",
        type=Path,
        default=_default_calendar_dir(),
        help="Directory that stores the calendar markdown files.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the generated patches without asking for confirmation.",
    )
    return parser


async def run_workflow(
    *,
    intent: Intent,
    current_date: str | None,
    calendar_dir: Path,
    apply: bool,
    prompt_on_write: bool = True,
) -> dict[str, object]:
    """Run one workflow, print a preview, and optionally write files."""
    resolved_date = current_date or date.today().isoformat()
    result = await graph.ainvoke(
        {
            "intent": intent,
            "current_date": resolved_date,
            "calendar_dir": str(calendar_dir),
        }
    )
    patches = build_patches(
        intent=intent,
        current_date=resolved_date,
        calendar_dir=calendar_dir,
        result=result,
    )

    sys.stdout.write(f"{result['response']}\n\n")
    sys.stdout.write("Planned file updates:\n")
    for patch in patches:
        sys.stdout.write(f"- {patch.path}: {patch.summary}\n")

    should_apply = apply or (prompt_on_write and confirm_apply())
    if should_apply:
        apply_file_patches(patches)
        sys.stdout.write("已写入文件。\n")
    else:
        sys.stdout.write("未写入文件。\n")

    result["patches"] = patches
    return result


def build_patches(
    *,
    intent: Intent,
    current_date: str,
    calendar_dir: Path,
    result: dict[str, object],
) -> list[FilePatch]:
    """Build concrete file patches from a graph result."""
    if intent == "weekly_plan":
        return build_weekly_plan_patches(
            calendar_dir=calendar_dir,
            current_date=current_date,
            weekly_plan=result["weekly_plan"],
            draft=result["draft"],
        )
    if intent == "temp_plan":
        return build_temp_plan_patches(
            calendar_dir=calendar_dir,
            current_date=current_date,
            weekly_plan=result["weekly_plan"],
            draft=result["draft"],
        )
    if intent == "daily_plan":
        return build_daily_plan_patches(
            calendar_dir=calendar_dir,
            current_date=current_date,
            daily_plan=result["daily_plan"],
            draft=result["draft"],
        )
    return build_daily_reflect_patches(
        calendar_dir=calendar_dir,
        current_date=current_date,
        daily_plan=result["daily_plan"],
        draft=result["draft"],
    )


def confirm_apply() -> bool:
    """Ask whether to write the generated file patches."""
    return input("是否写入这些文件？[y/N]: ").strip().lower() in {"y", "yes"}


def choose_intent() -> Intent:
    """Show the menu requested by the user and return the chosen workflow."""
    choice = input(
        "calendar-chat\n\n"
        "1. Weekly Plan\n"
        "2. Temp Plan\n"
        "3. Daily Plan\n"
        "4. Daily Reflect\n"
        "请选择:"
    ).strip()
    try:
        return MENU_OPTIONS[choice][1]
    except KeyError as error:
        raise SystemExit("无效选项，请输入 1-4。") from error


def prompt_for_date() -> str:
    """Return the user-selected date, defaulting to today."""
    default_date = date.today().isoformat()
    user_input = input(f"日期 (YYYY-MM-DD，默认 {default_date}): ").strip()
    return user_input or default_date


def _default_calendar_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "calendar"


def main() -> None:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    intent = args.intent or choose_intent()
    current_date = args.current_date or (prompt_for_date() if not args.intent else None)
    asyncio.run(
        run_workflow(
            intent=intent,
            current_date=current_date,
            calendar_dir=args.calendar_dir,
            apply=args.apply,
            prompt_on_write=not args.apply,
        )
    )


if __name__ == "__main__":
    main()
