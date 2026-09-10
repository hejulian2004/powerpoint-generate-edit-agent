# backend/MEMORY_MAP.md: 后端专属架构与上下文记忆地图

> **适用范围**：本文件为涉及 `backend/` 及 `pptx_agent_converter/` 相关开发、维护、调试、重构时的专项记忆地图。
> **跨端全局契约**：参见根目录 [`../MEMORY_MAP.md`](../MEMORY_MAP.md)。

---

## 1. 核心架构与职责划分

```
backend/
├── agent/                # LangGraph 状态机编排与多 Subagent 体系
│   ├── graph.py          # StateGraph 闭环节点与条件回退路由
│   ├── runtime.py        # Agent 会话生命周期、Transcript 唯一 owner、WS 发射与压缩判定
│   ├── mutation_gateway.py # 唯一写入口：Schema 校验/风险门控/确认拦截/事务回滚
│   ├── tools.py          # 统一图元工具库 (execute 统一派发器与快照)
│   ├── memory.py         # 系统级全局设计准则与用户偏好注入 (无 session 时回退)
│   ├── context_compressor.py # 上下文 Token 统计与 90% 自动语义压缩
│   └── subagents/        # 独立只读评审与执行子代理模块
│       ├── plan_critic.py    # PlanCriticSubagent (大纲结构盲审)
│       ├── executor.py       # ExecutorSubagent (纯规划器，产出 ExecutionPlan，无写权限)
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
├── eval/                 # 视觉质量评价与自愈分析 (SlideIR 引擎)
│   ├── layout_diff.py    # 几何碰撞、文本溢出与五维质量打分
│   ├── visual_critic.py  # 视觉审查与自动修复建议生成
│   └── renderer_snapshot.py # 确定性栅格快照渲染
├── evaluation/           # LayoutSpec 规则评估/补丁/自愈引擎 (生成图使用)
├── quality/              # 统一质量门面 (QualityService + 规范化契约)
│   ├── contracts.py      # QualityIssue/QualityReport、severity 归一化与适配器
│   └── service.py        # 唯一入口：委托 eval / evaluation，不做算法合并
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
                                       └── (通过) ──> executor_node (仅规划)
                                                          │
                                                          ▼
                                                    mutation_node (MutationGateway 唯一写入)
                                                          │
                                                          ▼
                                                   content_critic_node
                                                           ▲      │
                                                           └(打回)┤
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
2. **执行 Subagent 无写权限**：
   - `ExecutorSubagent` 仅产出 `ExecutorPlan`（工具调用清单），不得调用 `tools.execute`。
   - 所有写操作由 `mutation_node` 交给 `backend/agent/mutation_gateway.py` 统一提交。
3. **零上下文污染盲审 (Blind Auditing)**：
   - 各 Critic 不接收用户历史聊天记录或思考过程。
   - `PlanCritic`：仅接收大纲摘要与页数。
   - `ContentCritic`：仅接收提取出的纯文本清册（Text Manifest）。
   - `VisualCritic`：仅接收渲染栅格快照 + 元素坐标清册，**绝不修改文字**。
4. **确定性机械审查隔离**：
   - 格式与标签闭合验证由 `check_unclosed_tags_and_formatting`（栈算法）毫秒级完成（HTML/XML 标签闭合、`《》` `（）` `【】` `“”` 成对闭合、模板占位符泄漏检测）。
   - 格式不合规直接打回，无需调用语义 LLM。
5. **子代理专属返工记忆 (`SubagentSessionMemory`)**：
   - 记录存储在 `state["subagent_memories"]` 中，跨轮次持久化。
   - 返工时通过 `get_rework_context_summary()` 注入历史诊断与整改要求，完成多轮对比复验。

### 2.3 MutationGateway 写入口契约 (`agent/mutation_gateway.py`)
- **唯一写路径**：Agent 计划、用户确认、GUI 直接操作、自动自愈均经由 `MutationGateway.execute_tool_calls*`。
- **执行管线**：Schema 校验 → `RiskEnricher` → `ConfirmationGate`（低置信度挂起）→ `pres.transaction` 快照 → `tools.execute` → 失败回滚 → `last_target_id` 与遥测事件。
- **锁粒度**：网关仅在真正执行变更时获取 `session.mutation_lock`；Router/Planner/Executor/Critic 的 LLM 调用全程不持锁，GUI 拖拽与撤销不会被慢模型阻塞。Transport 不再包裹整轮 `run_turn`。
- **文档身份**：挂起确认绑定 `PPTSession.document_epoch` + `expected_revision`；整份替换（导入/生成/恢复检查点）轮换 epoch 并清空待确认项。
- **会话隔离**：`AgentMemory` 存于 `PPTSession.agent_memory`，`AgentRuntime` 不再持有全局记忆。

### 2.4 上下文注入 / 返工指令 / Deck 级评审
- **压缩上下文注入**：`AgentRuntime.run_turn` 将压缩后的 `state["messages"]` 交给 `ExecutorSubagent.plan_task`；Executor 提示词 = system（含压缩摘要锚点）+ 最近 8 轮对话 + 执行指令，当前用户轮已去重。Critic 仍保持盲审，不接收对话历史。
- **返工指令 (`rework_directive`)**：`content_critic_node` 在评审未通过时输出缺陷、建议与 `target_ids`；`executor_node` 将其注入执行提示词并强制返工模式，禁止再次调用 `generate_presentation`，只做精准文本修改。
- **Deck 级评审**：`mutation_node` 通过幻灯片指纹计算 `changed_slide_ids`；Content/Visual Critic 逐页审查所有变更页，聚合为 `content_review.slides` / `visual_review.slides`（含 `reviewed_slide_ids`、`failed_slide_ids`、`deck_average_score`），不再只审当前一页。`auto_correct_node` 对 `slides` 中每一张失败页逐个执行自愈，而非只修聚合主页面。

### 2.6 生成真实性门控 (`agent/grounding.py`)
- **无来源先追问**：`router_node` 识别数据型请求（财报/数据/指标/报告/benchmark 等关键词，或具体数值）后调用 `assess_generation_request`；若用户未提供可核验来源，则 `grounding_clarification` 直达 `summary_node`，不进入规划/执行，绝不编造内容。
- **有来源硬约束**：Executor 收到“只允许使用用户资料中的数字/事实”系统指令与资料原文；`mutation_node` 对 `generate_presentation` / `generate_slide_layout` 的数值断言做回溯校验，未在来源中出现的数字直接阻止写入并返回缺失数字清单。
- **占位豁免**：用户明确说明“示例/占位/不用真实数据”时跳过来源门控与数值校验。

### 2.5 统一质量门面 (`quality/`) 与 CORS 白名单
- **QualityService 是唯一质量入口**：交互式 Agent/WS/工具/管线统一调用 `QualityService.evaluate_slide / plan_remediation / review_slide / render_* / score_fidelity`；生成图统一调用 `QualityService.evaluate_layout / patches_for_issues / apply_layout_patches`。底层 `eval/`（SlideIR）与 `evaluation/`（LayoutSpec）保持原实现，不做算法合并；LayoutSpec 分支为惰性导入，避免把 PIL/python-pptx 带进交互热路径。
- **规范化契约**：`QualityIssue`/`QualityReport` 统一 severity 词表（critical/error/warning/info，`high|medium|low` 归一化），IR 缺陷码映射（如 `viewport_clipping -> overflow`）；`merge_reports` 保留最差分数与全部问题，不跨引擎平均分。
- **CORS 白名单**：`backend/main.py` 使用 `CORS_ORIGINS`（默认仅本地 Vite/Tauri origins），`"*"` 仅在显式配置时启用且自动关闭 credentials。

---

## 3. 上下文核算与 90% 自动压缩 (`agent/context_compressor.py`)

- **容量模式**：`128k`, `256k` (默认), `512k`, `1m`。
- **Token 估算**：CJK 字符按 ~1.6 token，英文/代码按词根估算。
- **触发阈值**：当前会话历史达到 **≥ 90%** 限制时，启动滑动窗口自动语义压缩：
  - 保留首条 System Prompt（含设计与排版规范）。
  - 保留末尾 4 轮最新对话上下文。
  - 将中间轮次提炼压缩为结构化锚点 `compressed_history_anchor`。
- **遥测事件广播**：每轮通过 `context_usage` WS 事件广播 `current_tokens`、`max_tokens`、`usage_percent`、`is_compressed` 等。
- **Transcript owner**：`AgentRuntime.run_turn()` 唯一负责追加 user / assistant 消息；WS 与 REST 行为一致，压缩结果不回写原始记录。
- **模型注入**：压缩上下文经 `ExecutorSubagent.plan_task` 注入执行模型（压缩锚点进 system，最近轮次进消息尾窗），不再只是前端指标。

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
   - 运行时写操作必须经由 `backend/agent/mutation_gateway.py`（唯一写入口），其内部调用 `backend/agent/tools.py:execute(tool_name, args, pres, history)`。
4. **几何同步**：修改图元坐标必须使用 `BaseElementIR.set_geometry(...)`（或 `translate`/`scale`）；直接赋值 `elem.x/width` 会使 `transform` 镜像对象过期，序列化回转时静默丢失改动。
5. **撤销/重做精确性**：
   - 简单图元操作使用 inverse-op 命令（`UpdateElementCommand`/`AddElementCommand`/`DeleteElementCommand`/slide 增删命令）。
   - 复合工具（`optimize_layout`/`align_elements`/`group_elements`/`ungroup_elements`/`batch_add_cards`/`clear_slide_elements`/`generate_slide_layout`/`set_slide_background`）记录 `SnapshotSlideCommand`；整稿级操作（`apply_theme`/`generate_presentation`）记录 `SnapshotCommand`。
   - 禁止 push 无 `before/after` 的空命令，否则 undo 永远失败形成“毒命令”；`tests/test_tool_undo_precision.py` 对所有复合工具做 undo→redo 深比较回归。

---

## 5. 后端测试与开发调试指令

```powershell
# 运行全部后端测试
.venv\Scripts\python.exe -m pytest -q

# 运行子代理闭环与返工记忆专项测试
.venv\Scripts\python.exe -m pytest tests/test_subagents_closed_loop.py tests/test_subagent_rework_memory.py -q

# 运行执行安全、文档身份、Transcript 与 LLM fail-fast 加固测试
.venv\Scripts\python.exe -m pytest tests/test_agent_execution_safety.py tests/test_confirmation_execution_gate.py tests/test_document_epoch.py tests/test_transcript_ownership.py tests/test_llm_fail_fast.py -q

# 运行第二阶段：上下文注入、返工指令、Deck 级评审与锁粒度测试
.venv\Scripts\python.exe -m pytest tests/test_context_injection.py tests/test_rework_directive.py tests/test_deck_level_review.py tests/test_lock_scope.py -q

# 运行统一质量门面与 CORS 白名单测试
.venv\Scripts\python.exe -m pytest tests/test_quality_service.py tests/test_cors_config.py -q

# 运行复合工具撤销/重做精确性测试
.venv\Scripts\python.exe -m pytest tests/test_tool_undo_precision.py -q

# 运行聊天生成真实性门控与 Deck 级自愈测试
.venv\Scripts\python.exe -m pytest tests/test_chat_generation_grounding.py tests/test_deck_auto_correct.py -q

# 运行上下文核算与 90% 自动压缩测试
.venv\Scripts\python.exe -m pytest tests/test_context_compressor.py -q

# 运行 5 维排版美学与视觉评估测试
.venv\Scripts\python.exe -m pytest tests/test_visual_eval.py -q
```
