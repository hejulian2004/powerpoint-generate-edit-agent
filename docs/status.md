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

### Fidelity Engine Hardening (PR6.1)
- **Capability Matrix**: `FidelityCapability` and `CapabilityDetector` distinguishing editable features from detect-only boundaries (chart / smartart / animation / master).
- **Partial-Failure Tolerant Import**: Corrupt parts emit warnings rather than hard-crashing.
- **Risk-Gated Mutation Policy**: `ActionRiskPolicy` ensuring proportional confidence thresholds (delete 0.95, move/resize 0.85, style 0.75).
- **Regression Guard & Rollback**: `FidelityRegressionGuard` protecting sub-metric fidelity limits (geometry <= 5 pts, text/style/visual <= 10 pts, critical floor 85).
- **Structured Fidelity Reporting**: `FidelityReport` surfacing actionable remediation issues for the agent.

### Research Paper Understanding Core (PR7.1)
- **Paper Intermediate Representation (`PaperIR`)**: Strongly-typed Pydantic v2 document model (`metadata`, `abstract`, `sections`, `figures`, `tables`, `contributions`, `methodology`, `experiments`, `limitations`).
- **Deterministic PDF Structural Extractor**: Zero-network heuristics extracting paper title, author bylines, reading order, numbered section hierarchy, figure/table captions, and raster image bounding boxes.
- **Optional LLM Semantic Enrichment**: Fault-tolerant reasoning layer to extract research contributions and limitations when a live API key is configured.
- **Deterministic Academic PDF Fixture**: Self-contained `tests/fixtures/paper/anomaly_agent.pdf` with automated generator `scripts/create_paper_fixtures.py`.
- **Full Acceptance Suite**: 16 dedicated unit and acceptance tests validating structural completeness and JSON round-trip stability.

---

## 2. In Progress

### Research Paper Presentation Agent (PR7)
- **PR7.2 Research Presentation Planner**:
  - Transforming `PaperIR` into a structured `PresentationPlan` (10-12 slide 15-minute academic lab meeting archetype).
  - Stable slide archetype mapping (Background, Problem, Motivation, Method, Experiments, Limitations, Conclusion).
- **PR7.3 Slide Semantic IR & Asset Understanding**:
  - `SlideSpec` semantic blocks (pipeline, comparison, metric highlights).
  - Figure classification (architecture, experiment, ablation) and table best-cell highlighting.
- **PR7.4 End-to-End Paper-to-PPTX Generation**:
  - Academic design themes (blue-accent minimal, dark keynote).
  - Unified PDF -> PPTX generation pipeline combining PR7 Planner + PR6 Fidelity Engine.

---

## 3. Future

- **Vision Auto-Correction**:
  - Full automated closed-loop where multi-modal vision models inspect rendered slide screenshots and self-correct layout overlaps or contrast flaws.
- **Multi-Agent Designer Swarm**:
  - Specialized agent teams (e.g., Content Researcher, Typographer, Graphic Designer, Layout Critic) collaborating asynchronously on full presentation decks.
- **Extended OOXML Capabilities**:
  - Editable support for charts, SmartArt, and master-slide inheritance (currently detect-only; charts/SmartArt noted as known coverage boundaries in the real-world benchmark).
