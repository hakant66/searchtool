from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

def hamming_distance(left: str, right: str) -> int:
    max_len = max(len(left), len(right))
    padded_l = left.ljust(max_len, "0")
    padded_r = right.ljust(max_len, "0")
    xor = int(padded_l, 16) ^ int(padded_r, 16)
    return xor.bit_count()


def image_visual_similarity(query_path: Path, candidate_path: Path, size: int = 128) -> float:
    """
    Pixel-level similarity used as a visual reranker.
    Returns score in [0, 1], where 1 means identical after normalization.
    """
    try:
        with Image.open(query_path) as q_img, Image.open(candidate_path) as c_img:
            q = np.asarray(
                q_img.convert("RGB").resize((size, size), Image.Resampling.LANCZOS),
                dtype=np.float32,
            )
            c = np.asarray(
                c_img.convert("RGB").resize((size, size), Image.Resampling.LANCZOS),
                dtype=np.float32,
            )
    except Exception:
        return 0.0
    mae = float(np.mean(np.abs(q - c)))
    return max(0.0, min(1.0, 1.0 - (mae / 255.0)))
