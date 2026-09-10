# MEMORY_MAP.md: PPT-Agent-Studio 全局架构与按需记忆地图

> **分层按需读取策略 (On-Demand Reading Guide)**：
> 为避免上下文膨胀，后续会话请根据具体开发任务**按需读取**对应模块的专属记忆文件：
> - 涉及 **后端 / Subagents / LLM 工具 / OOXML 转换** 时 ──> 请读取 [`backend/MEMORY_MAP.md`](./backend/MEMORY_MAP.md)
> - 涉及 **前端 / React / SVG 画布 / 吸附对齐 / Zustand / 样式** 时 ──> 请读取 [`frontend/MEMORY_MAP.md`](./frontend/MEMORY_MAP.md)
> - 涉及 **跨端通信协议 / 全局系统不变量** 时 ──> 请参考下述全局核心契约。

---

## 1. 系统核心公理与数据流向

```
       [用户自然语言 / Web 交互]
                  │
                  ▼
   [主 Agent: PPT 协同架构师 (唯一对外会话)]
                  │
        LangGraph 状态机编排
                  │
                  ▼
  [PPT-IR: 1280x720 规范矢量中间表示 (唯一真理源)]
       ┌──────────┴──────────┐
       ▼                     ▼
[前端 SVG 实时渲染]   [原生 OOXML 编解码转换]
(全双工 WebSocket)    (pptx_agent_converter)
       │                     │
  交互画布与吸附           无损导入导出 PPTX
```

### 全局三大不可变公理
1. **PPT-IR 是系统唯一状态真理 (Source of Truth)**：任何组件与模型不得直接破坏或绕过 PPT-IR。
2. **画布基准物理尺寸**：全局坐标系严格为 **1280 × 720** (16:9)。
3. **图元修改统一派发**：后端所有运行时图元写操作必须经由 `backend/agent/mutation_gateway.py`（唯一写入口），由网关统一完成 Schema 校验、风险门控、确认拦截与事务回滚，并内部调用 `backend/agent/tools.py:execute(tool_name, args, pres, history)`，确保 Undo/Redo 快照完整。
   - 几何修改必须走 `BaseElementIR.set_geometry`，避免 `transform` 镜像过期；复合工具使用状态快照命令，禁止空命令污染撤销栈。

### 一键启动入口
- **全栈一体化运行**：根目录执行 `python main.py`（自动检查产物、拉起 FastAPI 托管 API/WebSocket/SPA 并唤起浏览器）。
- **前端热重载开发**：根目录执行 `python main.py --dev`（并发拉起 Vite 5173 与后端 8000）。

---

## 2. 跨端通信与生命周期约定

- **WebSocket 统一信道**：`/ws/{sessionId}`。
- **用户会话唯一性**：前端聊天窗口只与主 Agent 交互，Subagent 状态仅通过遥测事件通知前端，不产生独立会话气泡。
- **上下文核算与 90% 自动压缩**：
  - 支持 `128k`, `256k` (默认), `512k`, `1m`。
  - Token 消耗达 90% 时后端自动滑动窗口语义压缩并广播 `context_usage` 事件；前端顶部环形进度规实时呈现。
  - `AgentRuntime.run_turn()` 是原始会话记录的唯一 owner（WS/REST 不再各自追加消息）；压缩结果仅面向模型，不回写 `session.messages`。
- **会话隔离与文档身份**：
  - `AgentMemory` 位于 `PPTSession.agent_memory`，跨会话严格隔离。
  - 挂起确认绑定 `document_epoch` + `expected_revision`；导入 / PPTSpec 生成 / 检查点恢复会轮换 epoch 并清空挂起确认。
- **锁粒度**：`session.mutation_lock` 仅由 MutationGateway 在实际写入时短暂持有；LLM 规划/评审期间不持锁，GUI 拖拽、撤销、直编不被慢模型阻塞。
- **质量入口统一**：所有布局质量调用走 `backend/quality/`（`QualityService` + `QualityIssue`/`QualityReport`）；底层 `eval/`（SlideIR）与 `evaluation/`（LayoutSpec）保持独立实现。
- **CORS 白名单**：仅允许 `CORS_ORIGINS` 配置的来源（默认本地 Vite/Tauri）；`"*"` 需显式配置且自动关闭 credentials。

---

## 3. 设计质感与视觉健康标准

1. **圆角规范**：商业设计卡片圆角严格控制在 `0.0 <= radius <= 3.0px`，严禁药丸形大圆角。
2. **OOXML `adj` 钳制**：`adj = int(clamp(radius_px / min_side_px, 0.0, 0.5) * 100000)`，区间合法在 `[0, 50000]`，禁止直写像素。
3. **文案精炼度**：观点先行，正文短句化（每条 ≤ 20~25 字）。
4. **五维视觉质量分**：
   `Geometry (30%) + Readability (20%) + Contrast (15%) + Balance (15%) + Aesthetics (20%)`。

---

## 4. 细分专属记忆导航

| 领域 | 专属记忆文件 | 关键涵盖内容 |
| :--- | :--- | :--- |
| **全栈全局** | [`MEMORY_MAP.md`](./MEMORY_MAP.md) | 系统数据流真理、跨端通信协议、全局设计质感标准 |
| **后端与智能体** | [`backend/MEMORY_MAP.md`](./backend/MEMORY_MAP.md) | LangGraph 闭环状态图、Subagent 盲审隔离、专属返工记忆、上下文 90% 自动压缩、OOXML 转换与 pytest 命令 |
| **前端与交互** | [`frontend/MEMORY_MAP.md`](./frontend/MEMORY_MAP.md) | React 19 + TypeScript + Zustand 状态树、SVG 1280x720 画布渲染、吸附对齐引擎、环形进度指示器与构建命令 |
