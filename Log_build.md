# 2026-05-14 Calendar Agent Build

## Step 1 - 固化文件契约

- 目标：先把 `calendar/` 当成稳定数据源，补路径解析和三类文件解析层。
- 修改：
  - 新增 `src/agent/calendar_files.py`
  - 新增 `tests/unit_tests/test_calendar_files.py`
- 设计：
  - 用 `CalendarPaths` 统一解析 `long-term / weekly / daily` 路径。
  - 用一级标题 section parser 处理周计划和日计划。
  - 用 ` ```sheet ` JSON 解析 Univer 长期目标表，并按行输出 `LongTermItem`。
- 最小测试：
  - `uv run python -m pytest tests/unit_tests/test_calendar_files.py`
  - `uv run ruff check src/agent/calendar_files.py tests/unit_tests/test_calendar_files.py`
- 结果：
  - 5 个单测通过。
  - 解析层可直接支撑后续图节点和补丁写入逻辑。

## Step 2 - 校正周起始契约

- 目标：让路径解析与现有样例 `calendar/2026-05-11 Weekly Plan.md` 保持一致。
- 修改：
  - `resolve_calendar_paths()` 从周日起始改为周一起始。
  - 同步更新路径解析测试。
- 最小测试：
  - `uv run python -m pytest tests/unit_tests/test_calendar_files.py`
  - `uv run ruff check src/agent/calendar_files.py tests/unit_tests/test_calendar_files.py`
- 结果：
  - 周计划文件路径已对齐需求文档与现有样例。
