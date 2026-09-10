# backend/MEMORY_MAP.md: 后端专属架构与上下文记忆地图

> **适用范围**：本文件为涉及 `backend/` 及 `pptx_agent_converter/` 相关开发、维护、调试、重构时的专项记忆地图。
> **跨端全局契约**：参见根目录 [`../MEMORY_MAP.md`](../MEMORY_MAP.md)。

---

## 1. 核心架构与职责划分

```
backend/
├── agent/                # LangGraph 状态机编排与多 Subagent 体系
│   ├── graph.py          # StateGraph 闭环节点与条件回退路由
│   ├── runtime.py        # Agent 会话生命周期、WS 发射与压缩判定
│   ├── tools.py          # 统一图元工具库 (execute 统一派发器与快照)
│   ├── memory.py         # 系统级全局设计准则与用户偏好注入
│   ├── context_compressor.py # 上下文 Token 统计与 90% 自动语义压缩
│   └── subagents/        # 独立只读评审与执行子代理模块
│       ├── plan_critic.py    # PlanCriticSubagent (大纲结构盲审)
│       ├── executor.py       # ExecutorSubagent (图元增删改执行)
│       ├── content_critic.py # ContentCriticSubagent (文案精炼与机械标签栈审查)
│       ├── visual_critic.py  # VisualCriticSubagent (5维排版美学盲审)
│       └── memory.py         # SubagentSessionMemory (专属私有返工记忆)
├── api/                  # FastAPI HTTP 路由与 REST 接口
│   ├── routes.py         # /api/settings, /api/status, /api/export 等
│   └── websocket.py      # /ws/{session_id} 全双工状态推送
├── ir/                   # PPT-IR 核心数据结构与补丁系统
│   ├── models.py         # PresentationIR, SlideIR, ElementIR (1280x720 坐标)
│   ├── patch.py          # HistoryManager, PatchRecord (撤销/重做)
│   ├── converter.py      # PPTX <-> PPT-IR 互转适配器
│   └── svg_renderer.py   # 后端确定性 SVG 矢量生成器
├── eval/                 # 视觉质量评价与自愈分析
│   ├── layout_diff.py    # 几何碰撞、文本溢出与五维质量打分
│   ├── visual_critic.py  # 视觉审查与自动修复建议生成
│   └── renderer_snapshot.py # 确定性栅格快照渲染
├── layout/               # 自动排版引擎与模板
│   ├── engine.py         # 布局计算引擎
│   ├── constraints.py   # 布局约束求解器
│   └── templates/        # title, comparison, pipeline, result 等模板
├── fidelity/             # 高保真 OOXML 主题、样式与字体引擎
└── server/               # WebSocket 服务器通信实现
```

---

## 2. 子代理闭环工作流机制 (Multi-Subagent Closed Loop)

### 2.1 状态机流转时序 (`agent/graph.py`)
```
router_node ──> planner_node ──> plan_critic_node
                     ▲                 │
                     └── (不通过打回) ─┤
                                       └── (通过) ──> executor_node ──> content_critic_node
                                                           ▲                 │
                                                           └── (不通过打回) ─┤
                                                                             └── (通过) ──> vision_critic_node
                                                                                                  │
                                                                   auto_correct_node ◄── (严重几何缺陷)
                                                                          │                       │
                                                                          └───────────────────────┴──> summary_node
```

### 2.2 子代理执行不变量
1. **纯只读评审机制**：
   - `PlanCriticSubagent`、`ContentCriticSubagent`、`VisualCriticSubagent` 绝不修改任何图元，绝不调用任何写工具。
   - 评审若发现问题，打回对应作者节点（`planner_node` 或 `executor_node`）。
2. **零上下文污染盲审 (Blind Auditing)**：
   - 各 Critic 不接收用户历史聊天记录或思考过程。
   - `PlanCritic`：仅接收大纲摘要与页数。
   - `ContentCritic`：仅接收提取出的纯文本清册（Text Manifest）。
   - `VisualCritic`：仅接收渲染栅格快照 + 元素坐标清册，**绝不修改文字**。
3. **确定性机械审查隔离**：
   - 格式与标签闭合验证由 `check_unclosed_tags_and_formatting`（栈算法）毫秒级完成（HTML/XML 标签闭合、`《》` `（）` `【】` `“”` 成对闭合、模板占位符泄漏检测）。
   - 格式不合规直接打回，无需调用语义 LLM。
4. **子代理专属返工记忆 (`SubagentSessionMemory`)**：
   - 记录存储在 `state["subagent_memories"]` 中，跨轮次持久化。
   - 返工时通过 `get_rework_context_summary()` 注入历史诊断与整改要求，完成多轮对比复验。

---

## 3. 上下文核算与 90% 自动压缩 (`agent/context_compressor.py`)

- **容量模式**：`128k`, `256k` (默认), `512k`, `1m`。
- **Token 估算**：CJK 字符按 ~1.6 token，英文/代码按词根估算。
- **触发阈值**：当前会话历史达到 **≥ 90%** 限制时，启动滑动窗口自动语义压缩：
  - 保留首条 System Prompt（含设计与排版规范）。
  - 保留末尾 4 轮最新对话上下文。
  - 将中间轮次提炼压缩为结构化锚点 `compressed_history_anchor`。
- **遥测事件广播**：每轮通过 `context_usage` WS 事件广播 `current_tokens`、`max_tokens`、`usage_percent`、`is_compressed` 等。

---

## 4. 原生 OOXML 约束与易错清单 (`pptx_agent_converter/`)

1. **圆角 `adj` 归一化规范**：
   - OOXML `adj` 必须规范化到 `[0, 50000]`：
     ```python
     adj = int(clamp(radius_px / min_side_px, 0.0, 0.5) * 100000)
     ```
   - **禁止**直接将像素值 `radius_px` 乘以 `100000` 传入 `adj`。
2. **卡片圆角质感约束**：
   - 商业风格卡片圆角严格控制在 `0.0 <= radius <= 3.0px`，严禁药丸形大圆角。
3. **图元修改必须通过原子派发**：
   - 必须通过 `backend/agent/tools.py:execute(tool_name, args, pres, history)` 执行。

---

## 5. 后端测试与开发调试指令

```powershell
# 运行全部后端测试
.venv\Scripts\python.exe -m pytest -q

# 运行子代理闭环与返工记忆专项测试
.venv\Scripts\python.exe -m pytest tests/test_subagents_closed_loop.py tests/test_subagent_rework_memory.py -q

# 运行上下文核算与 90% 自动压缩测试
.venv\Scripts\python.exe -m pytest tests/test_context_compressor.py -q

# 运行 5 维排版美学与视觉评估测试
.venv\Scripts\python.exe -m pytest tests/test_visual_eval.py -q
```
