from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sold_item_finder.core.db import Database


@dataclass(slots=True)
class TextSearchScopes:
    path_and_filename: bool = True
    metadata_fields: bool = True
    raw_structured_text: bool = True


@dataclass(slots=True)
class TextSearchResult:
    file_id: str
    title: str
    sku: str
    platform: str
    listing_id: str
    notes: str
    path: str
    image_paths: list[str]
    score: float
    snippet: str


class TextSearchService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def search(self, text: str, scopes: TextSearchScopes, limit: int = 50) -> list[TextSearchResult]:
        query = self._query_from_input(text, scopes)
        rows = self.db.search_text(query=query, limit=limit)
        dedupe: dict[str, TextSearchResult] = {}
        for row in rows:
            key = row["path"]
            score = float(-row["rank"])
            if key in dedupe:
                if len(dedupe[key].image_paths) < 3:
                    dedupe[key].image_paths.append(row["image_path"])
                continue
            dedupe[key] = TextSearchResult(
                file_id=row["file_id"],
                title=row["title"] or Path(row["path"]).name,
                sku=row["sku"] or "",
                platform=row["platform"] or "unknown",
                listing_id=row["listing_id"] or "",
                notes=row["notes"] or "",
                path=row["path"],
                image_paths=[row["image_path"]],
                score=score,
                snippet=row["snippet"] or "",
            )
        return list(dedupe.values())[:limit]

    def _query_from_input(self, text: str, scopes: TextSearchScopes) -> str:
        q = " ".join(text.strip().split())
        if not q:
            return ""
        columns: list[str] = []
        if scopes.path_and_filename:
            columns.extend(["path", "filename"])
        if scopes.metadata_fields:
            columns.extend(["platform", "title", "sku", "listing_id", "notes"])
        if scopes.raw_structured_text:
            columns.append("raw_text")
        if not columns:
            columns = ["path", "filename", "platform", "title", "sku", "listing_id", "notes", "raw_text"]

        if '"' in q:
            phrase = q.replace('"', "").strip()
            return " OR ".join(f"{col}:\"{phrase}\"" for col in columns)
        tokens = [t for t in q.split(" ") if t]
        return " OR ".join(" ".join(f"{col}:{token}" for token in tokens) for col in columns)
