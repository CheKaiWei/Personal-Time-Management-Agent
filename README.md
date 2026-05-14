# Calendar Agent

`calendar_agent` 是一个基于 LangGraph 的本地时间管理工作流工具。它不再是通用聊天模板，而是围绕同级目录 `../calendar/` 中的计划文件工作，提供 4 个可执行流程：

1. `Weekly Plan`
2. `Temp Plan`
3. `Daily Plan`
4. `Daily Reflect`

当前实现遵循“先读本地文件、生成草案、确认后写回”的最小闭环。规划逻辑是确定性的，本地测试不依赖网络。

## 目录约定

- 项目代码：`calendar_agent/`
- 输入输出文档目录：`../calendar/`
- 关键文件：
  - `calendar/{YYYY-MM} Long-term.univer.md`
  - `calendar/{week_start} Weekly Plan.md`
  - `calendar/{date}.md`

周起始日按周一计算。例如 `2026-05-14` 对应的周计划文件是 `calendar/2026-05-11 Weekly Plan.md`。

## 当前工作流

### 1. Weekly Plan

- 读取当月长期目标表和本周周计划。
- 选出 `3-5` 个优先 checkpoint 草案。
- 补齐 `Daily Links`。
- 为缺失的每日文件创建基础模板。

### 2. Temp Plan

- 读取周计划中的 `Temp Tasks`。
- 对临时任务做基础分类、紧急度判断和是否应进入本周计划的标记。
- 将结构化结果写回周计划的 `Temp Tasks` section。

### 3. Daily Plan

- 读取今天的日计划和本周周计划。
- 选择今天唯一的 checkpoint。
- 生成 `1-3` 个最小可执行单元（MEU）。
- 回写 `Calendar` 和 `Tasks`，保留 `Notes` 与 `Reflect`。

### 4. Daily Reflect

- 读取今天的 `Calendar / Tasks / Notes / Reflect`。
- 汇总时间块数量、任务完成数和备注数。
- 回写 `Reflect`。

## 安装

在 `calendar_agent/` 目录下执行：

```bash
uv sync
```

如果你不用 `uv`，也可以：

```bash
pip install -e .
```

安装后会注册 CLI：

```bash
calendar-chat
```

## 交互式使用

直接运行：

```bash
uv run calendar-chat
```

CLI 会显示：

```text
calendar-chat

1. Weekly Plan
2. Temp Plan
3. Daily Plan
4. Daily Reflect
请选择:
```

随后会继续询问日期，并在写入前展示草案和待更新文件。

## 脚本化使用

为了便于自动化和测试，CLI 也支持跳过菜单：

```bash
uv run calendar-chat --intent weekly_plan --date 2026-05-14 --calendar-dir ..\calendar
```

如果你要直接写入文件：

```bash
uv run calendar-chat --intent weekly_plan --date 2026-05-14 --calendar-dir ..\calendar --apply
uv run calendar-chat --intent temp_plan --date 2026-05-14 --calendar-dir ..\calendar --apply
uv run calendar-chat --intent daily_plan --date 2026-05-14 --calendar-dir ..\calendar --apply
uv run calendar-chat --intent daily_reflect --date 2026-05-14 --calendar-dir ..\calendar --apply
```

`--apply` 会跳过确认，直接写回 `calendar/` 文件。

## 文件写回规则

### Weekly Plan

会维护这些 section：

- `# Weekly Checkpoint`
- `# Temp Tasks`
- `# Daily Links`
- `# Adjustment Log`

### Daily Plan

会维护这些 section：

- `# Calendar`
- `# Tasks`
- `# Notes`
- `# Reflect`

其中：

- `Daily Plan` 只重写 `Calendar / Tasks`
- `Daily Reflect` 只重写 `Reflect`

## 开发说明

核心模块：

- `src/agent/calendar_files.py`
  - 路径解析
  - Markdown section 解析
  - Univer 长期目标表解析
- `src/agent/planner.py`
  - 四类工作流草案生成
- `src/agent/calendar_writes.py`
  - 草案转文件补丁
  - 文件落盘
- `src/agent/graph.py`
  - LangGraph 状态图
- `src/agent/cli.py`
  - 菜单与命令行入口

## 测试

运行全部测试：

```bash
uv run python -m pytest
```

运行静态检查：

```bash
uv run ruff check .
```

## 典型结果

执行 `Weekly Plan` 后，通常会看到：

- 本周 checkpoint 草案
- `Temp Tasks` 摘要
- 将要更新的周计划文件
- 将要创建的缺失日计划模板

执行 `Daily Plan` 后，通常会看到：

- 今日唯一 checkpoint
- `1-3` 个 MEU
- 将要更新的 `Calendar` 和 `Tasks`

执行 `Daily Reflect` 后，通常会看到：

- 时间块数量
- 任务完成/未完成概览
- 将要写回的 `Reflect` 内容
