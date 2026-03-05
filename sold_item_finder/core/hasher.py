from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image


def phash(image_path: Path) -> str:
    # Difference hash (dHash, 16x16): more discriminative than 8x8 average hash.
    with Image.open(image_path) as image:
        grayscale = image.convert("L").resize((17, 16), Image.Resampling.LANCZOS)
        arr = np.asarray(grayscale, dtype=np.uint8)
    diff = arr[:, 1:] > arr[:, :-1]  # 16x16 -> 256 bits
    bits = "".join("1" if flag else "0" for flag in diff.flatten())
    return f"{int(bits, 2):064x}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
