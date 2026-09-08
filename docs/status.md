# PPT-Agent-Studio Architecture Status & Roadmap

This document defines the current baseline state, active developments, and future roadmap for the PPT-Agent-Studio project.

---

## 1. Completed

### Core PPT-IR Representation & State
- **1280×720 ViewBox Standard**: Decoupled presentation state from binary file formats.
- **Strong Typing**: Pydantic / dataclass definitions covering slides, shapes, text runs, connectors, images, and visual styles.
- **Reversible Patch Engine (`HistoryManager`)**: Fine-grained JSON-patch style state tracking with bidirectional Undo/Redo capabilities.

### Agent Runtime & State Machine
- **LangGraph StateGraph Workflow**: Explicit state machine managing routing, planning, tool execution, visual critique, and user summaries.
- **Tool Suite**: Slide generation archetypes (card grid, timeline, KPI metrics, comparison), batch card creation, intelligent alignment, element manipulation, and typography formatting.
- **Multi-Role LLM Dispatch**: Support for general reasoning, vision critique, and fast parameter formatting.

### Interactive Canvas & Studio Frontend
- **Direct Canvas Manipulation**: Smooth element dragging and 8-direction precision resize handles with coordinate boundary constraints.
- **HTML5 Drag-and-Drop**: Placement of text, cards, shapes, and connectors from the top toolbar onto canvas coordinates.
- **Figma-Style Property Inspector**: Font family selection, font size steppers and presets, bold/italic, alignments, layout presets, and corner radius.
- **Real-Time WebSocket Sync**: Sub-second synchronization between user canvas actions, agent modifications, and multi-client broadcast.

### Package Validation & Regression Gates
- **OOXML Validator (`validate_pptx`)**: Inspects archive health, `presentation.xml`, slide collections, and relationships.
- **Multi-Fixture Smoke Test Gate (`test_roundtrip_smoke.py`)**: Validates the closed-loop pipeline (`PPTX -> OOXML Extractor -> PPT-IR -> OOXML Renderer -> PPTX`) across diverse presentation archetypes (`simple.pptx`, `academic.pptx`, `diagram.pptx`, `image-heavy.pptx`).
- **Conversion Fidelity Reporting (`ConversionReport`)**: Transparent tracking of converted vs. skipped elements with unified counting in `element_to_ir` to eliminate group double-counting, alongside explicit warning logs.

---

## 2. In Progress

- **OOXML Fidelity**:
  - Deepening support for complex text run properties (multi-level bullet lists, character spacing, hyperlinks).
  - Expanding shape geometry mappings and custom preset geometry preservation.
- **Complex Shape & Group Support**:
  - Improved preservation of deeply nested group hierarchies during roundtrip serialization.
  - Enhanced connector auto-routing and sticky connection points.
- **Fidelity Engine Hardening (PR6.1)**:
  - OOXML capability matrix (`FidelityCapability` / `CapabilityDetector`) surfaces which features are editable vs detect-only (chart / smartart / animation / master).
  - Partial-failure-tolerant import: corrupt theme / rels / media / slide parts produce a `partial` IR with warnings instead of crashing.
  - Per-action risk-gated semantic resolution (`ActionRiskPolicy`): delete 0.95 / move 0.85 / resize 0.85 / style 0.75.
  - Per-metric regression guard (`FidelityRegressionGuard`): geometry <= 5 pts, text/style/visual <= 10 pts, critical floor 85.
  - Stable element ids (`compute_stable_id`) for replay / undo / cross-render tracking.
  - Structured fidelity report (`FidelityReport`) with typed issues for the PR7 agent.
  - Real-world v2 benchmark (`tests/assets/real_world_v2/`, Composite >= 90%).

---

## 3. Future

- **Vision Auto-Correction**:
  - Full automated closed-loop where multi-modal vision models inspect rendered slide screenshots and self-correct layout overlaps or contrast flaws.
- **Multi-Agent Designer Swarm**:
  - Specialized agent teams (e.g., Content Researcher, Typographer, Graphic Designer, Layout Critic) collaborating asynchronously on full presentation decks.
- **Extended OOXML Capabilities**:
  - Editable support for charts, SmartArt, and master-slide inheritance (currently detect-only; charts/SmartArt noted as known coverage boundaries in the real-world benchmark).
