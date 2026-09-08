# Fidelity Engine (PR6 / PR6.1)

The Fidelity Engine is the reliable parsing / reconstruction / evaluation / repair
foundation beneath the PPT Agent. PR6.1 hardens it from an experimental high-fidelity
reconstructor into a stable infrastructure layer.

## Pipeline

```text
PPTX
  ↓
OOXML Parser (partial-failure tolerant)
  ↓
Capability Detection
  ↓
Semantic IR (PresentationIR + SemanticElementGraph + stable ids)
  ↓
Fidelity Evaluation (geometry / typography / style / visual)
  ↓
Safe Repair (per-metric FidelityRegressionGuard)
  ↓
Regression Validation (per-metric guard, rollback on violation)
  ↓
Export
```

## Public API

External consumers should depend ONLY on the stable facade:

```python
from backend.fidelity import FidelityEngine
from backend.eval.fidelity import (
    FidelityEvaluator,
    FidelityScore,
    FidelityRegressionGuard,
    FidelityDelta,
    build_fidelity_report,
    FidelityReport,
)
```

Do **not** import internals such as `ooxml_parser.py`, `style_resolver.py`, or
`relationship.py` directly; they are not part of the stable API.

### Import

```python
engine = FidelityEngine()
pres = engine.import_presentation("deck.pptx")      # PresentationIR
summary = engine.import_with_report("deck.pptx")    # status / warnings / capabilities
```

- `pres.capabilities` — detected OOXML feature presence per file.
- `pres.metadata["parse_status"]` — `"ok"` or `"partial"` (per-part failures recovered).
- `pres.metadata["parser_warnings"]` — parse + capability warnings.

### Evaluate / Diff / Report

```python
score = FidelityEngine.evaluate(orig_slide, recon_slide)   # FidelityScore
report = FidelityEngine.report(orig_slide, recon_slide)    # FidelityReport (structured issues)
```

The structured report is the PR7 input: it tells the agent exactly where and how to repair
(`type`, `element`, `expected`, `actual`, `severity`).

### Safe Repair

```python
guard = FidelityRegressionGuard()
accepted, reasons = guard.accepts(before_score, after_score)
```

A repair is committed only if the composite total does not drop AND no sub-dimension
regresses beyond its per-metric limit AND nothing falls below the critical floor.

## Support Matrix

| Feature       | Support      | Notes |
| ------------- | ------------ | ----- |
| Shape         | Full         | Preset geometry, adjust values, fills/borders/shadows |
| Text          | Full         | Runs, paragraphs, bullets, theme fonts |
| Image         | Full         | Media parts round-trip; corrupt-media magic-byte warning |
| Group         | Full         | Recursive nested groups |
| Theme         | Full         | Theme parts parsed into color/font scheme |
| Table         | Partial      | Parsed + round-trips for simple tables; complex tables deferred |
| Chart         | Detect only  | `chart` capability flag; NOT editable (PR7/PR8) |
| SmartArt      | Detect only  | `smartart` capability flag; NOT editable (PR7/PR8) |
| Animation     | Detect only  | `animation` capability flag; NOT editable |
| Master Slide  | Detect only  | structural; present in virtually every deck, excluded from warnings |

The Agent must check `PresentationIR.capabilities` before mutating: features flagged
`supported: false` (chart / smartart / animation) are reported and must not be edited.

## Reliability

- **Partial import**: corrupt `presentation.xml`, `theme*.xml`, `.rels`, `slideN.xml`, or
  `media/*` do not crash the import; failures are recorded as warnings and the resulting
  IR is marked `partial`. A package that is not a valid OOXML zip still raises.
- **No silent fallback**: a structurally broken semantic graph raises
  `SemanticResolutionError` instead of routing instructions to the wrong element.
- **Risk-gated resolution**: `ActionRiskPolicy` requires higher semantic confidence for
  destructive actions (delete >= 0.95, move/resize >= 0.85, style >= 0.75).
- **Regression guard**: repairs are rolled back when the composite total drops or any
  sub-dimension regresses (geometry > 5 pts, text/style/visual > 10 pts, or below 85).

## Benchmarks

- `tests/test_roundtrip_realworld_benchmark.py` — v1 corpus (Apache POI decks), with
  explicit `PASSING` / `KNOWN_BOUNDARY` manifests.
- `tests/test_realworld_v2_benchmark.py` — v2 business-archetype corpus; every committed
  deck must reach Composite Fidelity >= 90%.
- Provenance (source repo, license, sha256) is recorded in
  `tests/assets/real_world/REAL_WORLD_ORIGIN.md` and
  `tests/assets/real_world_v2/REAL_WORLD_V2_ORIGIN.md`.

## Rebuild assets

```text
python scripts/fetch_real_world_decks.py
```