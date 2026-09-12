"""Trusted cache-capability handling for the paper visual subsystem.

A ``cache_key`` is an opaque, server-issued capability handle. It is NEVER a
filesystem path. The only legal way to turn it into a path is::

    cache_key  ->  resolve_cache_dir()  ->  assert_within()

Every path deserialized from a cached artifact (``PaperVisualIR`` page assets and
region crops) is re-canonicalized on load and rejected if it escapes the cache
root. This makes it impossible for a client to point the vision pipeline at an
arbitrary file on the server.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Union

from .cache import DEFAULT_CACHE_ROOT, paper_cache_dir
from .errors import PaperCacheError
from .schema import PaperVisualIR

logger = logging.getLogger(__name__)

CACHE_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


def is_valid_cache_key(cache_key: object) -> bool:
    """A cache key must be exactly one lowercase SHA-256 hex digest."""
    return bool(isinstance(cache_key, str) and CACHE_KEY_RE.match(cache_key))


def resolve_cache_dir(
    cache_key: object,
    root: Optional[Union[str, Path]] = None,
) -> Path:
    """Validate ``cache_key`` as a capability handle and return the cache dir.

    Raises ``PaperCacheError`` for anything that is not a well-formed key or that
    resolves outside the cache root.
    """
    if not is_valid_cache_key(cache_key):
        raise PaperCacheError("INVALID_CACHE_KEY: cache_key is not a valid capability handle")
    base = Path(root) if root is not None else DEFAULT_CACHE_ROOT
    candidate = paper_cache_dir(str(cache_key), base)
    return assert_within(candidate, base)


def assert_within(path: Union[str, Path], root: Union[str, Path]) -> Path:
    """Resolve ``path`` and require it to live under ``root`` (fail closed)."""
    base = Path(root).resolve()
    resolved = Path(path).resolve()
    if resolved != base and base not in resolved.parents:
        raise PaperCacheError(
            f"PATH_ESCAPE: '{resolved}' is outside the trusted cache root '{base}'"
        )
    return resolved


def _canonicalize_path(
    raw_path: Optional[str],
    cache_dir: Path,
    *,
    label: str,
) -> Optional[str]:
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = cache_dir / candidate
    resolved = assert_within(candidate, cache_dir)
    if not resolved.exists():
        logger.warning("Cached %s missing on disk: %s", label, resolved)
    return str(resolved)


def canonicalize_visual_ir(visual_ir: PaperVisualIR, cache_dir: Union[str, Path]) -> PaperVisualIR:
    """Re-bind every page/crop path to the trusted cache root (in place).

    Raises ``PaperCacheError`` when any path escapes the root. Mutates and
    returns ``visual_ir`` for convenience.
    """
    root = Path(cache_dir).resolve()
    for page in visual_ir.pages:
        asset = page.page_asset
        asset.image_path = _canonicalize_path(
            asset.image_path, root, label=f"page {asset.page_number} image"
        ) or asset.image_path
        for region in page.regions:
            if not region.crop_path:
                continue
            region.crop_path = _canonicalize_path(
                region.crop_path, root, label=f"region {region.region_id} crop"
            )
    return visual_ir


__all__ = [
    "CACHE_KEY_RE",
    "is_valid_cache_key",
    "resolve_cache_dir",
    "assert_within",
    "canonicalize_visual_ir",
]
