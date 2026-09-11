"""Generation-path capability declaration (Phase 6 / Finding 9).

The generation path (Router -> Executor -> Mutation Gateway) may only author IR
features whose OOXML write-back is lossless. This module makes that contract
explicit and machine-checkable:

    GENERATION_CAPABILITIES  <=  EXPORT_SAFE_CAPABILITIES

`EXPORT_SAFE_CAPABILITIES` is derived from the fidelity engine support matrix
(editable features minus features with lossy write-back), so a feature can never
be generated and then silently degrade on export (e.g. tables).
"""

from __future__ import annotations

from ..fidelity.capability import LOSSY_WRITEBACK_FEATURES, SUPPORTED_FEATURES

# Features the generation path is permitted to author into the IR.
GENERATION_CAPABILITIES = frozenset({"shape", "text", "image", "group", "theme"})

# Features whose export round-trips losslessly: editable AND not lossy.
EXPORT_SAFE_CAPABILITIES = frozenset(SUPPORTED_FEATURES) - frozenset(
    LOSSY_WRITEBACK_FEATURES
)

assert GENERATION_CAPABILITIES <= EXPORT_SAFE_CAPABILITIES, (
    "GENERATION_CAPABILITIES must not include lossy / unsupported export features: "
    + ", ".join(sorted(GENERATION_CAPABILITIES - EXPORT_SAFE_CAPABILITIES))
)
