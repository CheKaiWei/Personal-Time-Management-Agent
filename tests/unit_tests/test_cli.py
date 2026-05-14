import pytest

from agent.cli import MENU_OPTIONS, choose_intent, run_workflow

pytestmark = pytest.mark.anyio


def _write_calendar_fixture(tmp_path) -> None:
    (tmp_path / "2026-05 Long-term.univer.md").write_text(
        """
```sheet
{"sheetOrder":["sheet-1"],"sheets":{"sheet-1":{"cellData":{"2":{"0":{"v":"Projects"},"1":{"v":"Tasks"}},"3":{"0":{"v":"Research"},"1":{"v":"Camera ready"},"4":{"v":"P1"},"5":{"v":"E1"},"7":{"v":"6h"}}}}}}
```
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "2026-05-11 Weekly Plan.md").write_text(
        """
# Weekly Checkpoint
- [ ] Existing checkpoint

# Temp Tasks
- [ ] Renew visa
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "2026-05-14.md").write_text(
        """
# Calendar

# Tasks

# Notes

# Reflect
""".strip(),
        encoding="utf-8",
    )


def test_choose_intent_reads_requested_menu_option(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "3")

    assert choose_intent() == MENU_OPTIONS["3"][1]


async def test_run_workflow_preview_does_not_write_files(tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    await run_workflow(
        intent="daily_reflect",
        current_date="2026-05-14",
        calendar_dir=tmp_path,
        apply=False,
        prompt_on_write=False,
    )

    daily_text = (tmp_path / "2026-05-14.md").read_text(encoding="utf-8")
    assert "已生成日复盘草案" not in daily_text


async def test_run_workflow_apply_writes_files(tmp_path) -> None:
    _write_calendar_fixture(tmp_path)

    await run_workflow(
        intent="daily_plan",
        current_date="2026-05-14",
        calendar_dir=tmp_path,
        apply=True,
        prompt_on_write=False,
    )

    daily_text = (tmp_path / "2026-05-14.md").read_text(encoding="utf-8")
    assert "推进 Existing checkpoint 的核心产出 60 分钟" in daily_text
