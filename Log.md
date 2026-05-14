# 2026-05-14

## 核心过程

1. 保留现有 LangGraph 单节点结构，只把占位返回替换为真实 OpenAI 对话调用，避免重构图结构。
2. 新增 `src/agent/config.py`，按优先级读取项目环境变量；未配置时回退到 `~/.codex/auth.json` 的 `OPENAI_API_KEY` 与 `~/.codex/config.toml` 的 `base_url/model`。
3. 新增 `src/agent/cli.py`，提供极简 terminal 对话入口；同时图节点支持 `messages` 输入，`langgraph dev` 下也可直接复用。
4. 补充最小测试，统一用 mock 验证配置加载和图调用，避免测试依赖真实网络。

## 结果

- 已添加 OpenAI 对话能力，入口：
  - terminal 单次调用：`uv run python -m agent.cli "你好"`
  - terminal 交互调用：`uv run python -m agent.cli`
  - UI 调用：`langgraph dev`
- 已更新 `README.md`、`.env.example`、`pyproject.toml`、`uv.lock`。
- 验证通过：
  - `uv run python -m pytest`
  - `uv run python -m ruff check .`
  - `uv run python -m agent.cli "你好，请用一句话自我介绍。"`

## 2026-05-14 langgraph dev 修复

1. 定位到 `langgraph dev` 按文件直接加载 `src/agent/graph.py`，此时 `src` 不在 `sys.path`，导致 `from agent.config ...` 报 `ModuleNotFoundError`。
2. 在 `src/agent/graph.py` 增加最小兜底：仅当文件被直接加载且包上下文缺失时，把项目 `src` 目录注入 `sys.path`。

- 验证结果：
  - `uv run python -m ruff check .`
  - `uv run python -m pytest`
- `langgraph dev` 成功启动
- `http://127.0.0.1:2024/docs` 返回 `200`

## 2026-05-14 Calendar Build

1. 新增 `src/agent/calendar_files.py`，固化 `calendar/` 的三类文件契约：周计划、日计划、长期表。
2. 先只做路径解析、Markdown section 拆分、Univer 表格行解析，不改图和 CLI。

结果：
- 已建立后续流程可复用的文件访问层。
- 最小验证通过：`uv run python -m pytest tests/unit_tests/test_calendar_files.py`

3. 根据 `calendar/2026-05-11 Weekly Plan.md` 样例，将 `week_start` 约定修正为“周一起始”。

结果补充：
- 周计划路径现与样例命名一致，避免后续读写错位一日。
