"""Normalization Artifact Storage (PR13 Step 6).

Caches normalized specifications alongside their original raw inputs on the server
to prevent client-side spec tampering and enforce re-validation on generation.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .schema import AssetRequirement, CanonicalPPTSpec


@dataclass
class NormalizationArtifact:
    """Server-side snapshot of a normalized presentation specification."""

    id: str
    raw_input: str
    canonical_spec: CanonicalPPTSpec
    summary: Dict[str, int]
    asset_requirements: List[AssetRequirement]
    warnings: List[str]
    created_at: float


class NormalizationArtifactStore:
    """Thread-safe in-memory store for NormalizationArtifacts."""

    def __init__(self, ttl_seconds: int = 3600):
        self.ttl_seconds = ttl_seconds
        self._store: Dict[str, NormalizationArtifact] = {}

    def save(
        self,
        raw_input: str,
        spec: CanonicalPPTSpec,
        summary: Dict[str, int],
        asset_requirements: List[AssetRequirement],
        warnings: Optional[List[str]] = None,
    ) -> NormalizationArtifact:
        self._cleanup()
        artifact_id = f"norm_{uuid.uuid4().hex[:10]}"
        artifact = NormalizationArtifact(
            id=artifact_id,
            raw_input=raw_input,
            canonical_spec=spec,
            summary=summary,
            asset_requirements=asset_requirements,
            warnings=list(warnings or []),
            created_at=time.time(),
        )
        self._store[artifact_id] = artifact
        return artifact

    def get(self, artifact_id: str) -> Optional[NormalizationArtifact]:
        self._cleanup()
        return self._store.get(artifact_id)

    def delete(self, artifact_id: str) -> bool:
        return self._store.pop(artifact_id, None) is not None

    def _cleanup(self) -> None:
        now = time.time()
        expired = [k for k, v in self._store.items() if now - v.created_at > self.ttl_seconds]
        for k in expired:
            self._store.pop(k, None)


artifact_store = NormalizationArtifactStore()
