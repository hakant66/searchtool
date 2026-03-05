from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


VISION_MODEL_NAME = "vision-local-rgbgray-v1"


def compute_vision_embedding(image_path: Path) -> list[float]:
    """
    Compact visual embedding:
    - 32-bin RGB histograms (96 dims)
    - 16x16 normalized grayscale grid (256 dims)
    Total: 352 dims float32
    """
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        arr = np.asarray(rgb, dtype=np.uint8)
        channels = [arr[:, :, i] for i in range(3)]
        hist_parts = []
        for ch in channels:
            hist, _ = np.histogram(ch, bins=32, range=(0, 256), density=True)
            hist_parts.append(hist.astype(np.float32))
        hist_vec = np.concatenate(hist_parts, axis=0)

        gray = rgb.convert("L").resize((16, 16), Image.Resampling.LANCZOS)
        gray_vec = (np.asarray(gray, dtype=np.float32).reshape(-1) / 255.0).astype(np.float32)

    vec = np.concatenate([hist_vec, gray_vec], axis=0).astype(np.float32)
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    return vec.tolist()
