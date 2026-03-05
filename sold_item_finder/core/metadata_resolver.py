from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


class MetadataResolver:
    METADATA_EXTS = {".json", ".csv", ".txt"}

    def resolve_for_image(self, image_path: Path) -> dict[str, str]:
        folder = image_path.parent
        merged: dict[str, str] = {
            "title": "",
            "sku": "",
            "listing_id": "",
            "notes": "",
            "platform": infer_platform(str(image_path).lower()),
            "raw_text": "",
        }
        raw_chunks: list[str] = []
        for meta in folder.iterdir():
            if not meta.is_file() or meta.suffix.lower() not in self.METADATA_EXTS:
                continue
            try:
                if meta.suffix.lower() == ".json":
                    payload = json.loads(meta.read_text(encoding="utf-8", errors="ignore"))
                    self._extract_fields_from_json(payload, merged, raw_chunks)
                elif meta.suffix.lower() == ".csv":
                    self._extract_fields_from_csv(meta, merged, raw_chunks)
                else:
                    raw_chunks.append(meta.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                # Ignore malformed metadata files; indexing should continue.
                continue
        merged["raw_text"] = " ".join(raw_chunks)[:4000]
        return merged

    def _extract_fields_from_json(
        self, payload: Any, merged: dict[str, str], raw_chunks: list[str]
    ) -> None:
        flat = _flatten_json(payload)
        raw_chunks.append(" ".join(flat.values()))
        field_candidates = {
            "title": ["title", "name", "item_title"],
            "sku": ["sku", "item_sku"],
            "listing_id": ["listing_id", "listing", "id"],
            "notes": ["notes", "description", "details"],
            "platform": ["platform", "marketplace", "site"],
        }
        for field, keys in field_candidates.items():
            if merged[field]:
                continue
            for key in keys:
                value = flat.get(key, "")
                if value:
                    merged[field] = value[:500]
                    break

    def _extract_fields_from_csv(
        self, path: Path, merged: dict[str, str], raw_chunks: list[str]
    ) -> None:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_text = " ".join(str(v) for v in row.values() if v is not None)
                raw_chunks.append(row_text)
                if not merged["title"]:
                    merged["title"] = str(row.get("title", "") or row.get("name", ""))[:500]
                if not merged["sku"]:
                    merged["sku"] = str(row.get("sku", ""))[:200]
                if not merged["listing_id"]:
                    merged["listing_id"] = str(row.get("listing_id", "") or row.get("id", ""))[:200]
                if not merged["notes"]:
                    merged["notes"] = str(row.get("notes", "") or row.get("description", ""))[:1000]
                if not merged["platform"]:
                    merged["platform"] = str(row.get("platform", ""))[:100]
                break


def infer_platform(text: str) -> str:
    if "ebay" in text:
        return "ebay"
    if "etsy" in text:
        return "etsy"
    if "vinted" in text:
        return "vinted"
    return "unknown"


def _flatten_json(payload: Any, prefix: str = "") -> dict[str, str]:
    output: dict[str, str] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            dotted = f"{prefix}.{key}" if prefix else str(key)
            output.update(_flatten_json(value, dotted))
    elif isinstance(payload, list):
        for idx, value in enumerate(payload):
            dotted = f"{prefix}.{idx}" if prefix else str(idx)
            output.update(_flatten_json(value, dotted))
    else:
        key = prefix.split(".")[-1] if prefix else "value"
        output[key] = str(payload)
    return output
