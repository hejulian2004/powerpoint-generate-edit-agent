"""Deterministic region cropping.

Crops are derived from the canonical page raster + normalized region boxes. The
vision model NEVER redraws a figure: it only proposes a normalized bbox, and this
module performs the actual pixel crop with Pillow.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Union

from .geometry import normalized_to_pixels
from .schema import PaperPageAsset, VisualRegion

logger = logging.getLogger(__name__)


def crop_regions(
    page_asset: PaperPageAsset,
    regions: Iterable[VisualRegion],
    output_dir: Union[str, Path],
    fmt: str = "webp",
) -> List[VisualRegion]:
    """Crop each region from its page image and populate ``crop_path`` in place.

    Regions whose crop cannot be produced keep ``crop_path=None``; the caller is
    expected to tolerate missing crops (they are best-effort visual evidence).
    """
    from PIL import Image

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    region_list = list(regions)
    if not region_list:
        return region_list

    try:
        source = Image.open(page_asset.image_path)
        source.load()
    except Exception as exc:
        logger.warning("Cannot open page image %s for cropping: %s", page_asset.image_path, exc)
        return region_list

    for region in region_list:
        try:
            left, top, right, bottom = normalized_to_pixels(
                region.bbox, page_asset.width, page_asset.height
            )
            crop = source.crop((left, top, right, bottom))
            filename = f"{region.region_id}.{fmt}"
            crop_path = out_dir / filename
            if fmt.lower() == "webp":
                crop.save(crop_path, "WEBP", quality=90, method=4)
            elif fmt.lower() == "png":
                crop.save(crop_path, "PNG")
            else:
                crop.save(crop_path)
            region.crop_path = str(crop_path)
        except Exception as exc:
            logger.warning("Region %s crop failed: %s", region.region_id, exc)
            region.crop_path = None

    return region_list


__all__ = ["crop_regions"]
