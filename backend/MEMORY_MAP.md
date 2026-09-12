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

# 运行论文多模态视觉理解（PaperVisualIR / 页面渲染 / 缓存 / 事实边界）测试
.venv\Scripts\python.exe -m pytest tests/paper_visual -q
```

---

## 6. 论文多模态视觉理解 (`paper_visual/`，S1)

论文视觉理解的独立子系统，为后续 LLM-native 演示设计提供视觉证据（视觉结构，而非事实）。

```
PDF
  │  pypdfium2  (唯一 canonical 栅格化器)
  v  pages/page_001.webp            (PaperPageAsset)
  │  vision LLM (role="vision")     (PaperVisualIR)
  v  PaperPageVisual / VisualRegion
  │  Pillow                         (确定性裁剪)
  v  crops/page_005_region_001.webp
```

- **模块**：`backend/paper_visual/`（`schema` / `renderer` / `crops` / `cache` / `context` / `analyzer` / `geometry` / `constants` / `errors`）。
- **缓存**：内容寻址 `output/paper_cache/{sha256(pdf)+renderer_version+dpi}/`，跨会话复用，`manifest.json` + `paper_visual_ir.json`。
- **入口**：`POST /api/paper/analyze`（vision-gated，只回传 PaperIR + pages + PaperVisualIR，**不生成 deck、不写 PresentationIR**）。
- **开关**：`PAPER_VISION_ENABLED`（关闭→降级，不调 Vision）；`PAPER_PAGE_RENDER_DPI`（默认 144）；`PAPER_VISION_BATCH_SIZE`（默认 4）。
- **不变量**：
  1. **pypdfium2 是唯一页面栅格化器**；`pdfplumber` 只做文本/行/图片 bbox 结构抽取，绝不渲染页面；Pillow 只做裁剪/编码。
  2. `PaperIR`（文本）是唯一事实权威；`PaperVisualIR` 只描述视觉结构，**不得引入数字或科学主张**。事实边界复用 `backend/agent/grounding.py` + `backend/pptspec/validator.py`。
  3. Vision 只接收归一化 `[0,1]` 页内坐标；`PaperIR.BBox`（pdfplumber 点，top-left）在区域匹配前用 pypdfium2 `get_size()`（含旋转）归一化。
  4. Vision 不可用时降级为 pages + 文本 PaperIR，不抛异常。
- **测试 fixture**：`tests/fixtures/paper/multicase_10p.pdf`（10 页多场景，由 `tests/paper_visual/make_fixture.py` 确定性生成；`.gitignore` 对 `tests/fixtures/**/*.pdf` 放行）。

---

## 7. LLM-native 演示设计 (`design/`，S2)

两阶段自由式设计：LLM 拥有视觉设计，确定性代码只做编译与硬校验；**无 layout catalog / 无 layout_type 枚举**。legacy 模板仅作**逐页 fallback**。

```
PaperIR + PaperVisualIR + contact sheet
  │  art_director.design_deck           (role="vision" 有图 / "reasoning" 纯文本)
  v  DeckArtDirection + PresentationPlan (自由式，可直接决定页数与每页职责)
  │  layout_designer.design_deck_layouts (逐页 role="vision")
  v  LLMLayoutPlan (绝对坐标 1280x720，无 layout_type)
  │  layout_compiler.compile_llm_layout + hard_validate_layout
  v  LayoutSpec  ──(校验失败→反馈重试≤max_layout_repair_rounds)──> 单页模板 fallback
```

- **模块**：`backend/design/`（`schema` / `prompts` / `json_utils` / `context_builder` / `art_director` / `layout_schema` / `layout_context` / `layout_designer` / `validator_feedback` / `layout_compiler`）。
- **入口**：`backend/layout/engine.py` 暴露薄封装 `compile_llm_layout` / `compile_llm_deck_layout`（**惰性导入** `backend.design`，避免循环依赖）。
- **开关**：`LLM_NATIVE_LAYOUT_ENABLED`（关闭→整条链路回退 legacy）；`MAX_LAYOUT_REPAIR_ROUNDS`（默认 2）。
- **上下文预算（三级）**：① 全论文视觉分析（batch）→ ② 艺术总监（文本摘要 + 视觉摘要 + contact sheet，低分辨率）→ ③ 单页设计（只附该页相关 1..3 页高分辨率 + crop，最多 6 张图）。`context_builder`/`layout_context` 负责裁剪。
- **不变量**：
  1. **LLM 拥有设计**：坐标、配色、层次、留白由模型决定；代码**只校验、不代选**；schema 中不存在 `layout_type`/`template_name`/`composition`。
  2. 任何含 `image_url` 的调用必须 `role="vision"`，纯文本推理用 `role="reasoning"`。
  3. **硬校验**（`hard_validate_layout`）：越界 / 前景重叠 / 不可读字号（<10 硬错，<12 警告）/ 非法 `source_block_id` / 图片长宽比损坏（<0.1 或 >10）。修复反馈经 `format_layout_validation_feedback` 回喂，最多 `max_layout_repair_rounds` 轮；仍失败才**逐页** fallback。
  4. 卡片圆角由编译器确定性夹取到 `[0, 3]px`（遵守全局美学不变量）；`opacity` 由 schema 约束 `[0,1]`。
  5. Art director 失败（无 key / 非法 JSON）→ `(None, None)`；`build_plan_and_direction` 回退 `default_art_direction()` + legacy planner。
  6. 事实边界：prompt 明令不得从图像推断数字；数字只能来自 `PaperIR`。
- **测试**：`tests/design/`（31 项）覆盖 schema（无模板枚举）、编译器硬校验、上下文装配、art director 角色分流、修复循环与逐页 fallback。

### 7.1 视觉批评 / 颜色校验 / 美学精炼（S3，Phase 6–8）

编译后的 `DeckLayoutSpec` 在持久化前进入只读质检与有界美化闭环：

```
LayoutSpec ──> visual_critic.critique_deck   (规则 + 可选 role="vision" 多模态)
                   │  + color_validator.validate_deck_colors (WCAG 对比度 + 语义绑定)
                   v  SlideCritique {score<=80 或 hard-invalid => needs_refinement}
             aesthetic_refiner.refine_deck_aesthetics
                   │  仅对 flagged slide 重跑 design_slide_layout（附 critic 反馈）
                   v  候选须 hard-valid 且 score 不回退才接受（<=max_aesthetic_refinement_rounds）
             refined DeckLayoutSpec (metadata: aesthetic_rounds / critique_scores / color_valid)
```

- **模块**：`backend/design/`（`visual_critic` / `color_validator` / `aesthetic_refiner`）。
- **开关**：`MAX_AESTHETIC_REFINEMENT_ROUNDS`（默认 2）。
- **复用（不重复造引擎）**：`backend.evaluation.evaluator.RuleBasedEvaluator`（规则缺陷）、`backend.eval.layout_diff.calculate_contrast_ratio` + `parse_hex_color`（WCAG）。
- **不变量**：
  1. **Critic 严格只读**：只产出诊断与建议，绝不修改 layout/文字/事实；`needs_refinement = 非 hard-valid | 有 error 缺陷 | score < 80`。
  2. **内容不可变**：精炼只允许 `design_slide_layout` 重发几何/样式/配色；反馈指令明确要求"Preserve all text content exactly"。
  3. 候选须重新 `hard_validate_layout` 且 critic 分数**不回退**才接受，否则保留原布局并终止该页精炼。
  4. 无可用 LLM client 时精炼为 no-op（budget=0）。
  5. 彩色校验初始仅报告；`validate_deck_colors` 不写回。
- **测试**：`tests/design/`（新增 19 项）覆盖 hex 校验、语义绑定漂移、WCAG 阈值（正文 4.5 / 大字 3.0）、容器背景识别、多模态分数融合与降级、只读反馈指令、有界精炼与非回退接受、无 client no-op。

### 7.2 Paper → PPT 端到端编排（S4，Phase 9–12）

`generation_graph` 新增 paper 分支（`source_type="paper"`），与既有 PPTSpec 分支并列：

```
START ──entry_route──┬─ source_type=="pptspec" ─> ingest -> normalize -> validate -> compile_slidespec -> layout_node ─┐
                     └─ source_type=="paper"   ─> paper_plan_node ─(PAPER_IR_MISSING? END)-> paper_design_node ─────────┤
                                                                                                                        v
                     compile_presentation_ir_node -> preview -> visual_review -> persist_session_node (CAS) -> END
```

- **paper_plan_node**：`design.build_plan_and_direction`（LLM art director → fallback 默认 art direction）→ `map_presentation_plan_to_deck_spec`；记录 `generation_mode` / `layout_source` / `fallback_reason`。
- **paper_design_node**：`design_deck_layouts`（逐页自由式 + 硬校验修复）+ `refine_deck_aesthetics`（美学精炼，图中 `include_multimodal=False`，多模态留待外部 raster 注入）。
- **持久化**：`persist_session_node` 仍为唯一写入点，`session.commit_replacement`（CAS `base_document_epoch`/`base_revision` + epoch 轮换，`source="rest"`）。provenance 落 `PresentationIR.metadata["generation"]`：`mode` / `source_type="paper"` / `layout_source` / `fallback_reason?` / `paper`{title,page_count,figure_count,table_count} / `paper_visual`{page_count,vision_model} / `art_direction`{design_concept,visual_language,primary_accent} / `duration_minutes`。
- **接口**：`POST /api/paper/generate`（Body：`session_id`(必填) + `paper_ir`(必填，来自 `/api/paper/analyze`) + 可选 `paper_visual_ir`/`user_prompt`/`duration_minutes`）。错误码：无 session_id→400，无 paper_ir→400，非法 IR→422，stale→409，管线异常→500。
- **不变量**：paper 分支不经过 `validate_truthfulness`（事实边界由 PaperIR 权威 + §7 上下文约束保证）；写路径只经 `commit_replacement`，绝不绕过 CAS。
- **测试**：`tests/design/test_paper_pipeline_e2e.py`（LLM-native 全链路、legacy fallback、缺 PaperIR 终止）+ `tests/paper_visual/test_paper_generate_route.py`（校验错误码、端到端持久化与 metadata）。
