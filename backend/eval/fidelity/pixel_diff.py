"""PixelDiff: Pure-Python and Pillow based perceptual image comparison (SSIM, MSE, PSNR).

Zero external dependencies: computes Structural Similarity Index (SSIM) and pixel
delta heatmap using standard Python and PIL.
"""

from __future__ import annotations
import math
import io
from dataclasses import dataclass
from typing import Tuple, Optional, Any, Union
from PIL import Image, ImageChops, ImageEnhance


@dataclass
class PixelDiffResult:
    ssim: float        # 0.0 to 1.0 (1.0 = identical)
    mse: float         # Mean Squared Error (0.0 = identical)
    psnr: float        # Peak Signal-to-Noise Ratio (inf or >40dB = high fidelity)
    diff_ratio: float  # Percentage of differing pixels (> 5/255 delta)
    diff_image: Optional[Image.Image] = None

    def to_dict(self) -> dict:
        return {
            "ssim": round(self.ssim, 4),
            "mse": round(self.mse, 2),
            "psnr": round(self.psnr, 2) if not math.isinf(self.psnr) else 999.0,
            "diff_ratio": round(self.diff_ratio, 4),
        }


class PixelDiffEngine:
    """Computes perceptual and structural visual similarity between slide images."""

    @classmethod
    def compare_images(
        cls,
        img1: Union[Image.Image, str, bytes],
        img2: Union[Image.Image, str, bytes],
        target_size: Tuple[int, int] = (320, 180),
        generate_heatmap: bool = False
    ) -> PixelDiffResult:
        im1 = cls._load_image(img1)
        im2 = cls._load_image(img2)

        # Standardize size and mode (RGB)
        im1 = im1.convert("RGB")
        im2 = im2.convert("RGB")
        if im1.size != target_size:
            im1_resized = im1.resize(target_size, Image.Resampling.BILINEAR)
        else:
            im1_resized = im1

        if im2.size != target_size:
            im2_resized = im2.resize(target_size, Image.Resampling.BILINEAR)
        else:
            im2_resized = im2

        w, h = target_size
        p1 = list(im1_resized.get_flattened_data() if hasattr(im1_resized, "get_flattened_data") else im1_resized.getdata())
        p2 = list(im2_resized.get_flattened_data() if hasattr(im2_resized, "get_flattened_data") else im2_resized.getdata())
        n_pixels = w * h

        # 1. MSE & Pixel Delta
        sq_err = 0.0
        diff_count = 0
        for (r1, g1, b1), (r2, g2, b2) in zip(p1, p2):
            dr = r1 - r2
            dg = g1 - g2
            db = b1 - b2
            err = (dr * dr + dg * dg + db * db) / 3.0
            sq_err += err
            if abs(dr) > 5 or abs(dg) > 5 or abs(db) > 5:
                diff_count += 1

        mse = sq_err / n_pixels
        psnr = 10.0 * math.log10((255.0 * 255.0) / mse) if mse > 1e-6 else float("inf")
        diff_ratio = diff_count / n_pixels

        # 2. Block-based SSIM on grayscale luminance
        gray1 = im1_resized.convert("L")
        gray2 = im2_resized.convert("L")
        ssim_val = cls._compute_ssim(gray1, gray2, block_size=16)

        # 3. Diff heatmap
        diff_img = None
        if generate_heatmap:
            diff_img = ImageChops.difference(im1_resized, im2_resized)
            diff_img = ImageEnhance.Brightness(diff_img).enhance(3.0)

        return PixelDiffResult(
            ssim=round(max(0.0, min(1.0, ssim_val)), 4),
            mse=round(mse, 2),
            psnr=round(psnr, 2) if not math.isinf(psnr) else 999.0,
            diff_ratio=round(diff_ratio, 4),
            diff_image=diff_img
        )

    @staticmethod
    def _compute_ssim(gray1: Image.Image, gray2: Image.Image, block_size: int = 16) -> float:
        w, h = gray1.size
        p1 = list(gray1.get_flattened_data() if hasattr(gray1, "get_flattened_data") else gray1.getdata())
        p2 = list(gray2.get_flattened_data() if hasattr(gray2, "get_flattened_data") else gray2.getdata())

        c1 = (0.01 * 255.0) ** 2  # 6.5025
        c2 = (0.03 * 255.0) ** 2  # 58.5225

        ssim_total = 0.0
        block_count = 0

        for by in range(0, h - block_size + 1, block_size):
            for bx in range(0, w - block_size + 1, block_size):
                b1_vals = []
                b2_vals = []
                for y in range(by, by + block_size):
                    offset = y * w
                    for x in range(bx, bx + block_size):
                        idx = offset + x
                        b1_vals.append(p1[idx])
                        b2_vals.append(p2[idx])

                n = len(b1_vals)
                mu1 = sum(b1_vals) / n
                mu2 = sum(b2_vals) / n

                var1 = sum((v - mu1) ** 2 for v in b1_vals) / n
                var2 = sum((v - mu2) ** 2 for v in b2_vals) / n
                covar = sum((v1 - mu1) * (v2 - mu2) for v1, v2 in zip(b1_vals, b2_vals)) / n

                num = (2.0 * mu1 * mu2 + c1) * (2.0 * covar + c2)
                den = (mu1 * mu1 + mu2 * mu2 + c1) * (var1 + var2 + c2)
                block_ssim = num / den if den != 0 else 1.0

                ssim_total += block_ssim
                block_count += 1

        if block_count == 0:
            return 1.0
        return ssim_total / block_count

    @staticmethod
    def _load_image(source: Union[Image.Image, str, bytes]) -> Image.Image:
        if isinstance(source, Image.Image):
            return source
        if isinstance(source, bytes):
            return Image.open(io.BytesIO(source))
        if isinstance(source, str):
            return Image.open(source)
        raise ValueError(f"Unsupported image input type: {type(source)}")
