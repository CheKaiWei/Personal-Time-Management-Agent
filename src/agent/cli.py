"""Terminal entrypoint for the calendar planning workflows."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from langgraph.types import Command

from agent.calendar_files import resolve_calendar_paths
from agent.calendar_writes import (
    FilePatch,
    apply_file_patches,
    build_daily_plan_patches,
    build_daily_reflect_patches,
    build_temp_plan_patches,
    build_weekly_plan_patches,
)
from agent.graph import Intent, graph

DocumentTarget = Literal["weekly_plan", "daily_plan", "long_term"]
CommandKind = Literal["workflow", "open_document", "help", "exit"]

MENU_OPTIONS: dict[str, tuple[str, Intent]] = {
    "1": ("Weekly Plan", "weekly_plan"),
    "2": ("Temp Plan", "temp_plan"),
    "3": ("Daily Plan", "daily_plan"),
    "4": ("Daily Reflect", "daily_reflect"),
}
CANCEL_WORDS = {"exit", "quit", "cancel", "取消"}
APPROVE_WORDS = {"通过", "pass", "approve", "approved", "ok", "yes", "y"}
RETURN_MENU_WORDS = {"back", "menu", "return", "返回"}
HELP_WORDS = {"help", "?", "帮助"}
OPEN_WORDS = ("open", "show", "read", "view", "打开", "查看")

WORKFLOW_ALIASES: dict[Intent, tuple[str, ...]] = {
    "weekly_plan": ("weekly plan", "week plan", "weekly", "周计划", "本周计划"),
    "temp_plan": ("temp plan", "temp", "临时计划", "临时任务"),
    "daily_plan": ("daily plan", "today plan", "daily", "日计划", "今日计划", "今天计划"),
    "daily_reflect": ("daily reflect", "daily review", "reflect", "日复盘", "今日复盘"),
}
DOCUMENT_ALIASES: dict[DocumentTarget, tuple[str, ...]] = {
    "weekly_plan": ("weekly plan", "week plan", "weekly", "周计划"),
    "daily_plan": ("daily plan", "today", "today plan", "daily", "日计划", "今日计划", "今天计划"),
    "long_term": ("long term", "long-term", "longterm", "长期", "长期目标"),
}


@dataclass(frozen=True)
class UserCommand:
    """Parsed user command from the interactive prompt or CLI argument."""

    kind: CommandKind
    intent: Intent | None = None
    document: DocumentTarget | None = None


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
    parser.add_argument(
        "command",
        nargs="*",
        help='Optional natural-language command, for example "open weekly plan".',
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
    """Run one workflow, allow multi-turn Q&A, and optionally write files."""
    ensure_backend_ready(calendar_dir)
    resolved_date = current_date or get_default_current_date()
    base_thread_id = build_thread_id(intent=intent, current_date=resolved_date, calendar_dir=calendar_dir)
    base_payload: dict[str, Any] = {
        "intent": intent,
        "current_date": resolved_date,
        "calendar_dir": str(calendar_dir),
    }
    review_feedback_history: list[str] = []
    previous_result: dict[str, Any] | None = None
    review_round = 0

    while True:
        thread_id = build_review_thread_id(base_thread_id=base_thread_id, review_round=review_round)
        payload = dict(base_payload)
        if previous_result is not None:
            payload["qa_history"] = previous_result.get("qa_history", [])
            payload["review_feedback_history"] = review_feedback_history
            payload["previous_draft"] = previous_result["draft"]

        result = await run_planning_round(payload=payload, thread_id=thread_id)
        if result.get("cancelled"):
            return result

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

        result["patches"] = patches
        result["thread_id"] = thread_id

        if apply:
            apply_file_patches(patches)
            sys.stdout.write("Files written.\n")
            return result

        if not prompt_on_write:
            sys.stdout.write("Files not written.\n")
            return result

        review_action = ask_for_review_action()
        if review_action == "__return_to_menu__":
            sys.stdout.write("Returning to menu.\n")
            result["return_to_menu"] = True
            return result
        if review_action is None:
            sys.stdout.write("Files not written.\n")
            result["cancelled"] = True
            return result
        if is_approval(review_action):
            apply_file_patches(patches)
            sys.stdout.write("Files written.\n")
            return result

        review_feedback_history.append(review_action)
        previous_result = result
        review_round += 1
        sys.stdout.write("Revising draft based on your feedback...\n")


async def invoke_graph(payload: dict[str, Any] | Command, config: dict[str, Any]) -> dict[str, Any]:
    """Invoke the graph with state or a resume command."""
    return await graph.ainvoke(payload, config)


async def run_planning_round(*, payload: dict[str, Any], thread_id: str) -> dict[str, Any]:
    """Run one planning round, including any LLM clarification interrupts."""
    config = {"configurable": {"thread_id": thread_id}}
    current_payload: dict[str, Any] | Command = payload

    while True:
        result = await invoke_graph(current_payload, config)
        interrupt_payload = extract_interrupt_payload(result)
        if not interrupt_payload:
            return result

        answer = ask_llm_question(interrupt_payload)
        if answer == "__return_to_menu__":
            sys.stdout.write("Returning to menu.\n")
            return {"return_to_menu": True, "thread_id": thread_id}
        if answer is None:
            sys.stdout.write("Workflow cancelled.\n")
            return {"cancelled": True, "thread_id": thread_id}
        current_payload = Command(resume=answer)


def extract_interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first interrupt payload if the graph paused for user input."""
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None

    interrupt = interrupts[0]
    return interrupt.value if hasattr(interrupt, "value") else None


def ask_llm_question(interrupt_payload: dict[str, Any]) -> str | None:
    """Show an LLM question and collect the next user answer."""
    message = str(interrupt_payload.get("message", "")).strip()
    question = str(interrupt_payload.get("question", "")).strip()
    turn = interrupt_payload.get("turn")

    if message:
        sys.stdout.write(f"Assistant ({turn}): {message}\n")
    sys.stdout.write(f"Assistant ({turn}): {question}\n")

    try:
        answer = input("You: ").strip()
    except EOFError:
        return None

    if answer.lower() in RETURN_MENU_WORDS:
        return "__return_to_menu__"
    if answer.lower() in CANCEL_WORDS:
        return None
    return answer


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


def build_thread_id(*, intent: Intent, current_date: str, calendar_dir: Path) -> str:
    """Build a stable thread id for interrupt/resume."""
    paths = resolve_calendar_paths(calendar_dir, current_date)
    if intent == "weekly_plan":
        return f"week:{paths.week_start}"
    if intent == "temp_plan":
        return f"temp:{current_date}"
    if intent == "daily_plan":
        return f"day:{current_date}"
    return f"day_reflect:{current_date}"


def build_review_thread_id(*, base_thread_id: str, review_round: int) -> str:
    """Build an isolated thread id for each review regeneration round."""
    if review_round == 0:
        return base_thread_id
    return f"{base_thread_id}:review:{review_round}"


def get_default_current_date() -> str:
    """Return today's local date for CLI defaults."""
    return date.today().isoformat()


def get_backend_status(calendar_dir: Path) -> dict[str, object]:
    """Return a lightweight backend health snapshot for the CLI."""
    return {
        "graph_ready": graph is not None,
        "calendar_dir_exists": calendar_dir.exists(),
        "calendar_dir": str(calendar_dir),
    }


def ensure_backend_ready(calendar_dir: Path) -> None:
    """Fail fast if the CLI backend is not ready for a workflow run."""
    status = get_backend_status(calendar_dir)
    if not status["graph_ready"]:
        raise RuntimeError("Backend graph is not ready.")
    if not status["calendar_dir_exists"]:
        raise RuntimeError(f"Calendar directory does not exist: {calendar_dir}")


def format_backend_status(status: dict[str, object]) -> str:
    """Render a concise backend status line for the interactive menu."""
    readiness = "ready" if status["graph_ready"] and status["calendar_dir_exists"] else "error"
    return (
        f"Backend: {readiness} | "
        f"graph={'ok' if status['graph_ready'] else 'missing'} | "
        f"calendar_dir={'ok' if status['calendar_dir_exists'] else 'missing'}"
    )


def ask_for_review_action() -> str | None:
    """Ask for iterative review feedback before applying file writes."""
    try:
        action = input(
            "Enter feedback to revise, `通过` to write files, `返回` to go back, or `取消` to stop: "
        ).strip()
    except EOFError:
        return None

    if action.lower() in RETURN_MENU_WORDS:
        return "__return_to_menu__"
    if not action or action.lower() in CANCEL_WORDS:
        return None
    return action


def is_approval(action: str) -> bool:
    """Return whether the review action means the user approves the draft."""
    return action.strip().lower() in APPROVE_WORDS


def parse_user_command(text: str) -> UserCommand | None:
    """Parse a free-form menu command into a workflow or document action."""
    normalized = _normalize_user_text(text)
    if not normalized:
        return None
    if normalized in CANCEL_WORDS:
        return UserCommand(kind="exit")
    if normalized in HELP_WORDS:
        return UserCommand(kind="help")
    if normalized in MENU_OPTIONS:
        return UserCommand(kind="workflow", intent=MENU_OPTIONS[normalized][1])

    if _contains_any(normalized, OPEN_WORDS):
        document = _match_document_target(normalized)
        if document:
            return UserCommand(kind="open_document", document=document)

    intent = _match_workflow_intent(normalized)
    if intent:
        return UserCommand(kind="workflow", intent=intent)

    return None


def choose_command(*, calendar_dir: Path | None = None) -> UserCommand:
    """Show the interactive prompt and return a parsed command."""
    status = format_backend_status(get_backend_status(calendar_dir or _default_calendar_dir()))
    prompt = (
        "calendar-chat\n"
        f"{status}\n\n"
        "1. Weekly Plan\n"
        "2. Temp Plan\n"
        "3. Daily Plan\n"
        "4. Daily Reflect\n"
        "You can also type commands like:\n"
        "- weekly plan\n"
        "- open weekly plan\n"
        "- open daily plan\n"
        "- open long term\n"
        "Type `help` for examples or `exit` to quit.\n"
        "Choose: "
    )

    while True:
        choice = input(prompt).strip()
        command = parse_user_command(choice)
        if command is not None:
            return command
        sys.stdout.write(
            "Unknown command. Enter 1-4, a workflow name, or a command like `open weekly plan`.\n"
        )


def choose_intent(*, calendar_dir: Path | None = None) -> Intent:
    """Show the prompt requested by the user and return the chosen workflow."""
    while True:
        command = choose_command(calendar_dir=calendar_dir)
        if command.kind == "exit":
            raise SystemExit(0)
        if command.kind == "help":
            sys.stdout.write(help_text())
            continue
        if command.kind == "workflow" and command.intent is not None:
            return command.intent
        sys.stdout.write("This command is not a workflow. Try `weekly plan` or choose 1-4.\n")


def prompt_for_date() -> str | None:
    """Return the user-selected date, defaulting to today."""
    default_date = get_default_current_date()
    user_input = input(f"Date (YYYY-MM-DD, default {default_date}): ").strip()
    if user_input.lower() in RETURN_MENU_WORDS or user_input.lower() in CANCEL_WORDS:
        return None
    return user_input or default_date


def show_document(*, document: DocumentTarget, current_date: str, calendar_dir: Path) -> dict[str, str]:
    """Render one calendar document in the terminal."""
    if not calendar_dir.exists():
        raise RuntimeError(f"Calendar directory does not exist: {calendar_dir}")

    path = resolve_document_path(
        document=document,
        current_date=current_date,
        calendar_dir=calendar_dir,
    )
    header = f"{document_label(document)}: {path}"
    if not path.exists():
        sys.stdout.write(f"{header}\nFile does not exist yet.\n")
        return {"document": document, "path": str(path), "content": ""}

    content = path.read_text(encoding="utf-8").rstrip()
    sys.stdout.write(f"{header}\n\n{content}\n")
    return {"document": document, "path": str(path), "content": content}


def resolve_document_path(
    *,
    document: DocumentTarget,
    current_date: str,
    calendar_dir: Path,
) -> Path:
    """Resolve a document target into the matching file path."""
    paths = resolve_calendar_paths(calendar_dir, current_date)
    if document == "weekly_plan":
        return paths.weekly_plan_file
    if document == "daily_plan":
        return paths.daily_plan_file
    return paths.long_term_file


def document_label(document: DocumentTarget) -> str:
    """Return a short human-readable document label."""
    if document == "weekly_plan":
        return "Weekly Plan"
    if document == "daily_plan":
        return "Daily Plan"
    return "Long-term"


def help_text() -> str:
    """Return concise help for the interactive prompt."""
    return (
        "Examples:\n"
        "- 1\n"
        "- weekly plan\n"
        "- daily reflect\n"
        "- open weekly plan\n"
        "- 打开weekly plan\n"
        "- open long term\n"
    )


async def run_text_command(
    *,
    command_text: str,
    current_date: str | None,
    calendar_dir: Path,
    apply: bool,
) -> dict[str, object]:
    """Run a single natural-language command from the CLI."""
    command = parse_user_command(command_text)
    if command is None:
        raise SystemExit(
            "Unknown command. Use a workflow like `weekly plan` or a file action like `open weekly plan`."
        )

    if command.kind == "exit":
        return {"cancelled": True}
    if command.kind == "help":
        sys.stdout.write(help_text())
        return {"help": True}

    resolved_date = current_date or get_default_current_date()
    if command.kind == "open_document" and command.document is not None:
        document_result = show_document(
            document=command.document,
            current_date=resolved_date,
            calendar_dir=calendar_dir,
        )
        return {
            "command": command_text,
            "current_date": resolved_date,
            **document_result,
        }

    if command.intent is None:
        raise RuntimeError("Workflow command is missing an intent.")

    return await run_workflow(
        intent=command.intent,
        current_date=resolved_date,
        calendar_dir=calendar_dir,
        apply=apply,
        prompt_on_write=not apply,
    )


async def run_interactive_session(*, calendar_dir: Path, apply: bool) -> None:
    """Run the top-level prompt loop and allow users to switch actions."""
    while True:
        command = choose_command(calendar_dir=calendar_dir)
        if command.kind == "exit":
            return
        if command.kind == "help":
            sys.stdout.write(help_text())
            continue

        current_date = prompt_for_date()
        if current_date is None:
            sys.stdout.write("Returning to menu.\n")
            continue

        if command.kind == "open_document" and command.document is not None:
            show_document(
                document=command.document,
                current_date=current_date,
                calendar_dir=calendar_dir,
            )
        else:
            if command.intent is None:
                raise RuntimeError("Workflow command is missing an intent.")
            result = await run_workflow(
                intent=command.intent,
                current_date=current_date,
                calendar_dir=calendar_dir,
                apply=apply,
                prompt_on_write=True,
            )
            if result.get("return_to_menu") or result.get("cancelled"):
                continue

        follow_up = input("Press Enter to continue, or type exit to quit: ").strip()
        if follow_up.lower() in CANCEL_WORDS:
            return


def _default_calendar_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "calendar"


def _normalize_user_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)


def _match_workflow_intent(text: str) -> Intent | None:
    for intent, aliases in WORKFLOW_ALIASES.items():
        if any(alias in text for alias in aliases):
            return intent
    return None


def _match_document_target(text: str) -> DocumentTarget | None:
    for document, aliases in DOCUMENT_ALIASES.items():
        if any(alias in text for alias in aliases):
            return document
    return None


def main() -> None:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    if args.intent and args.command:
        parser.error("Use either --intent or a natural-language command, not both.")

    if args.command:
        asyncio.run(
            run_text_command(
                command_text=" ".join(args.command),
                current_date=args.current_date,
                calendar_dir=args.calendar_dir,
                apply=args.apply,
            )
        )
        return

    if args.intent:
        asyncio.run(
            run_workflow(
                intent=args.intent,
                current_date=args.current_date,
                calendar_dir=args.calendar_dir,
                apply=args.apply,
                prompt_on_write=not args.apply,
            )
        )
        return

    asyncio.run(
        run_interactive_session(
            calendar_dir=args.calendar_dir,
            apply=args.apply,
        )
    )


if __name__ == "__main__":
    main()
