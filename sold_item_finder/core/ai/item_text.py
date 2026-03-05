from __future__ import annotations

from pathlib import Path


def build_item_text(metadata: dict[str, str], path: str, filename: str) -> str:
    fields = [
        metadata.get("title", ""),
        metadata.get("platform", ""),
        metadata.get("sku", ""),
        metadata.get("listing_id", ""),
        metadata.get("notes", ""),
    ]
    path_tokens = _tokenize_path(path)
    filename_tokens = " ".join(Path(filename).stem.replace("_", " ").replace("-", " ").split())
    payload = " | ".join(
        value.strip()
        for value in [
            " ".join(v for v in fields if v),
            path_tokens,
            filename_tokens,
        ]
        if value.strip()
    )
    return payload[:1200]


def _tokenize_path(path: str) -> str:
    tokens = []
    for part in Path(path).parts[-6:]:
        cleaned = part.replace("_", " ").replace("-", " ").strip()
        if cleaned:
            tokens.append(cleaned)
    return " ".join(tokens)
