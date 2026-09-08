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
- **Smoke Test Gate (`test_roundtrip_smoke.py`)**: Validates the closed-loop pipeline (`PPTX -> OOXML Extractor -> PPT-IR -> OOXML Renderer -> PPTX`).
- **Conversion Fidelity Reporting (`ConversionReport`)**: Transparent tracking of converted vs. skipped elements and explicit warning logs.

---

## 2. In Progress

- **OOXML Fidelity**:
  - Deepening support for complex text run properties (multi-level bullet lists, character spacing, hyperlinks).
  - Expanding shape geometry mappings and custom preset geometry preservation.
- **Complex Shape & Group Support**:
  - Improved preservation of deeply nested group hierarchies during roundtrip serialization.
  - Enhanced connector auto-routing and sticky connection points.
- **Visual Diff & Regression Tracking**:
  - Automated pixel-level SVG fast comparison to measure rendering delta before and after agent edits.

---

## 3. Future

- **Vision Auto-Correction**:
  - Full automated closed-loop where multi-modal vision models inspect rendered slide screenshots and self-correct layout overlaps or contrast flaws.
- **Multi-Agent Designer Swarm**:
  - Specialized agent teams (e.g., Content Researcher, Typographer, Graphic Designer, Layout Critic) collaborating asynchronously on full presentation decks.
- **Extended OOXML Capabilities**:
  - Selective pass-through and editing support for tables, charts, and smart diagrams.
