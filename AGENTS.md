# AGENTS.md

> **Architecture & Memory Maps (On-Demand Reading Strategy)**:
> To optimize context usage, read the relevant memory map based on your task scope:
> - **Global Architecture & Cross-Cutting Invariants**: [`MEMORY_MAP.md`](./MEMORY_MAP.md)
> - **Backend / Subagents / LLM Tools / OOXML Converter**: [`backend/MEMORY_MAP.md`](./backend/MEMORY_MAP.md)
> - **Frontend / React / SVG Canvas / Snapping / State Store**: [`frontend/MEMORY_MAP.md`](./frontend/MEMORY_MAP.md)

## Repository Overview
Full-stack AI slide creation platform powered by **PPT-IR** (Intermediate Representation) as canonical truth:
- **Backend (`backend/`)**: FastAPI + WebSockets + LangGraph workflow + multi-subagent orchestration.
- **Frontend (`frontend/`)**: React 19 + TypeScript + Vite + Tailwind CSS v4 + Zustand + SVG canvas.
- **OOXML Converter (`pptx_agent_converter/`)**: Native Python OOXML parsing and generation framework.
- **Tests (`tests/`)**: 520+ pytest tests covering IR, layout engine, PPTX conversion, and subagent closed loops.

---

## Developer Commands

### Environment & Python (.venv)
Always use the repo virtual environment:
```powershell
.venv\Scripts\python.exe -m pytest tests/test_subagents_closed_loop.py -q
.venv\Scripts\python.exe -m pytest tests/test_visual_eval.py -q
.venv\Scripts\python.exe -m pytest -q
```
- **Single test file**: `.venv\Scripts\python.exe -m pytest tests/<file>.py -q`
- **Specific test function**: `.venv\Scripts\python.exe -m pytest tests/<file>.py -k "<test_name>" -q`

### Frontend (`frontend/`)
```powershell
# Run from frontend directory (use workdir: "frontend")
npm run build        # Typecheck + Vite build: tsc -b && vite build
npm run lint         # Oxlint fast linter
npm run test         # Vitest test suite
```

---

## Architecture & Subagent Closed-Loop Workflow

### Closed-Loop Pipeline Order
The LangGraph workflow (`backend/agent/graph.py`) enforces strict multi-subagent separation:
```
User Prompt
    │
    ▼
router_node
    │
    ▼
planner_node (Drafts presentation/slide outline)
    │
    ▼
plan_critic_node (PlanCriticSubagent blind audit)
    ├── Rejected ──> Loop back to planner_node (reworks using audit feedback)
    └── Approved
          │
          ▼
    executor_node (ExecutorSubagent plans tool calls only)
          │
          ▼
    mutation_node (MutationGateway: risk gate + confirmation + transaction)
          │
          ▼
    content_critic_node (ContentCriticSubagent deck-level text/structure audit)
          ├── Rejected ──> Loop back to executor_node with `rework_directive`
          │                 (targeted text edits only; no deck regeneration)
          └── Approved
                │
                ▼
          vision_critic_node (VisualCriticSubagent 5-dimension aesthetic critique)
                ├── Critical Defects ──> auto_correct_node (Safe layout auto-repair)
                └── Healthy / Max Iterations
                      │
                      ▼
                summary_node -> END
```

### Critical Subagent Invariants
1. **Critic Subagents are Strictly Read-Only**:
   - `PlanCriticSubagent`, `ContentCriticSubagent`, and `VisualCriticSubagent` NEVER execute tools or modify slide objects.
   - If audit fails, state machine returns to `planner_node` or `executor_node`.
2. **Context Isolation (Blind Auditing)**:
   - Critics NEVER receive author chat history, conversation memory, or planning chain-of-thought.
   - `PlanCriticSubagent` receives only abstract outline string and slide count.
   - `ContentCriticSubagent` receives only extracted text manifest.
   - `VisualCriticSubagent` receives only the raster snapshot (data URI) + element coordinate manifest.
   - `VisualCriticSubagent` focuses strictly on geometry, alignment, whitespace, and aesthetics—NEVER semantic text editing.
3. **Mechanical vs Semantic Inspection Boundary**:
   - Structural/Formatting Validation (unclosed tags `<b>...</b>`, mismatched brackets `《》`, unrendered placeholders) must be verified mechanically (deterministic code/stack checks).
   - Content review focuses strictly on brevity, clarity, and narrative coherence.
   - Visual review focuses purely on layout, alignment, margins, and aesthetics.
4. **Subagent Private History Continuity (`SubagentSessionMemory`)**:
   - Each subagent has its own isolated `SubagentSessionMemory` persisted in `state["subagent_memories"]`.
   - On rework loops, subagents preserve their round history and inspect whether previous issues were addressed.
5. **Context Window Accounting & Auto-Compression**:
   - Main agent is the SOLE conversational endpoint exposed to the user; Subagents audit via telemetry without polluting chat messages.
   - Configurable context window (128k, 256k, 512k, 1m).
   - Token accounting with automatic sliding-window semantic compression triggered at **>= 90%** of the context limit.
   - Frontend renders a circular progress gauge in `ChatPanel` reflecting real-time token capacity.
   - `AgentRuntime.run_turn()` is the single owner of the raw transcript; compression is model-facing only and never rewrites `session.messages`.
   - The compressed context is actually fed to the Executor planning LLM (bounded tail window + compressed anchor); critics remain blind.
6. **Mutation Gateway is the Only Writer**:
   - `ExecutorSubagent` is a pure planner returning `ExecutorPlan`; it has no tool execution authority.
   - `mutation_node` commits plans through `backend/agent/mutation_gateway.py`, the single choke point for schema validation, risk enrichment, confirmation gating, and transaction rollback.
   - User confirmations, direct GUI actions, and automated remediation also dispatch through the gateway.
   - The gateway acquires `session.mutation_lock` only around actual mutations: LLM planning/critique never blocks GUI edits.
   - Pending confirmations are bound to the session's `document_epoch` + revision; deck replacement (import / PPTSpec generation / checkpoint restore) rotates the epoch and clears them.
   - `AgentMemory` is session-scoped (`PPTSession.agent_memory`), never global.
7. **Deck-Level Review & Rework Directives**:
   - `mutation_node` reports `changed_slide_ids` (content fingerprints); critics audit every changed non-empty slide, aggregating a deck review with per-slide results.
   - A Content Critic rejection emits `rework_directive` (slide_id, target_ids, defects, recommendations); the Executor must perform precise text edits and must never regenerate the whole deck.

---

## Key Technical Conventions

### 1. Canvas Dimensions & OOXML Coordinates
- **Canvas Size**: Canonical resolution is **1280x720** (16:9).
- **OOXML Adj Clamping**: `adj` values in `pptx_agent_converter/renderer/shape_renderer.py` must be normalized to `[0, 50000]`:
  `adj = int(clamp(radius_px / min_side_px, 0.0, 0.5) * 100000)`. Never pass raw pixels > 50000 to OOXML `adj`.

### 2. Design & Aesthetics Rules
- **No Pill/Large-Radius Cards**: Card radii must be subtle (`0.0 <= radius <= 3.0px`).
- **Concise Text**: Keep bullet points concise (<= 25 chars per item).
- **Language Default**: Primary content is Chinese (retain standard technical terms in Chinese).
- **5-Dimension Visual Score**:
  `Geometry (30%) + Readability (20%) + Contrast (15%) + Balance (15%) + Aesthetics (20%)`.

### 3. Tool Calling & Patch History
- Runtime mutations must dispatch through `backend/agent/mutation_gateway.py` (the single writer); the gateway validates, risk-gates, and transactionally calls `backend/agent/tools.py:execute(tool_name, args, pres, history)`.
- Reversible mutations are tracked in `HistoryManager` (`backend/ir/patch.py`).
- Mock LLM fallback is test-only: set `APP_ENV=test` and `MOCK_LLM=true`; production without an API key fails fast.
