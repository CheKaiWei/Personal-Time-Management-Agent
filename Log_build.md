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

## Step 3 - 建最小状态图与四个草案分支

- 目标：先把控制流搭起来，严格区分 `weekly_plan / temp_plan / daily_plan / daily_reflect`，但这一步不落盘。
- 修改：
  - 重写 `src/agent/graph.py`
  - 新增 `src/agent/planner.py`
  - 重写 `tests/integration_tests/test_graph.py`
  - 清理 `tests/unit_tests/test_configuration.py` 中旧聊天输入兼容测试
- 设计：
  - `load_context` 只解析日期和必要文件。
  - `route_intent` 只负责路由，不混入规划逻辑。
  - 四个节点都产出 `draft + response`，后续写入层再消费 `draft`。
  - 规划先走确定性规则，避免测试依赖网络和模型。
- 最小测试：
  - `uv run python -m pytest tests/unit_tests/test_calendar_files.py tests/unit_tests/test_configuration.py tests/integration_tests/test_graph.py`
  - `uv run ruff check src/agent/graph.py src/agent/planner.py tests/integration_tests/test_graph.py tests/unit_tests/test_configuration.py`
- 结果：
  - 4 条图分支都能成功返回草案。
  - 图结构已从“对话模板”切换到“时间管理流程模板”。

## Step 4 - 建补丁与写回层

- 目标：让四类草案可以独立转成文件补丁，并在不依赖 CLI 的情况下完成落盘测试。
- 修改：
  - 新增 `src/agent/calendar_writes.py`
  - 新增 `tests/unit_tests/test_calendar_writes.py`
- 设计：
  - 用 `FilePatch` 表达单文件更新。
  - Weekly Plan 会补齐 `Daily Links` 和缺失的日计划模板。
  - Daily Plan 只改 `Calendar / Tasks`，保留 `Notes / Reflect`。
  - Daily Reflect 只改 `Reflect`。
- 最小测试：
  - `uv run python -m pytest tests/unit_tests/test_calendar_writes.py`
  - `uv run ruff check src/agent/calendar_writes.py tests/unit_tests/test_calendar_writes.py`
- 结果：
  - 四类写入补丁都能在临时目录成功应用。

## Step 5 - 菜单 CLI、README 与真实文件演示

- 目标：把用户入口切到最终期望的 `calendar-chat` 菜单，并用真实 `calendar/` 做一次端到端写回。
- 修改：
  - 重写 `src/agent/cli.py`
  - 新增 `tests/unit_tests/test_cli.py`
  - 重写 `README.md`
  - 调整 `src/agent/planner.py`，使 `Daily Plan` 优先对齐已有 `Calendar` 时间块
  - 扩展 `tests/integration_tests/test_graph.py` 覆盖该对齐逻辑
- 设计：
  - CLI 默认走交互菜单，满足最终展示要求。
  - `--intent` + `--apply` 保留给测试、脚本和批量演示。
  - `Daily Plan` 若当天已存在时间块，则优先用首个时间块对应 checkpoint 生成 `Tasks`，避免 `Calendar` 与 `Tasks` 脱节。
- 最小测试：
  - `uv run python -m pytest`
  - `uv run ruff check .`
- 真实演示：
  - `uv run python -m agent.cli --intent weekly_plan --date 2026-05-14 --calendar-dir ..\\calendar --apply`
  - `uv run python -m agent.cli --intent temp_plan --date 2026-05-14 --calendar-dir ..\\calendar --apply`
  - `uv run python -m agent.cli --intent daily_plan --date 2026-05-14 --calendar-dir ..\\calendar --apply`
  - `uv run python -m agent.cli --intent daily_reflect --date 2026-05-14 --calendar-dir ..\\calendar --apply`
- 真实写回结果：
  - 更新 `../calendar/2026-05-11 Weekly Plan.md`
  - 创建 `../calendar/2026-05-13.md`
  - 更新 `../calendar/2026-05-14.md`
  - 创建 `../calendar/2026-05-16.md`
- 结果：
  - 项目已从模板聊天 CLI 切换到时间管理菜单 CLI。
  - README 已覆盖安装、运行、脚本模式、文件规则和测试说明。

## Step 6 - Restore LLM Decisions And Multi-Turn Q&A

- Goal:
  - align the implementation with the original design document
  - let the LLM make the four core planning decisions
  - allow multi-turn clarification before finalizing a draft
- Changes:
  - rewrote `src/agent/planner.py` into an LLM-driven planning layer
  - updated `src/agent/graph.py` to use `interrupt()` and `Command(resume=...)`
  - compiled the graph with `InMemorySaver`
  - updated `src/agent/cli.py` to loop through LLM follow-up questions
  - rewrote `tests/integration_tests/test_graph.py`
  - rewrote `tests/unit_tests/test_cli.py`
  - rewrote `README.md`
- Design:
  - LLM owns:
    - weekly checkpoint selection
    - temp task structuring
    - daily checkpoint + MEU selection
    - daily reflection Q&A and summary
  - deterministic code still owns:
    - file parsing
    - file patches
    - final markdown writes
    - fallback normalization for malformed LLM output
- Validation:
  - `uv run python -m pytest`
  - `uv run ruff check .`
  - real dry-run through the graph using `temp_plan`
- Result:
  - the project is now LLM-driven at the planning layer
  - multi-turn Q&A works through LangGraph pause/resume instead of ad-hoc CLI loops
