from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sold_item_finder.core.ai.vision_embedding import VISION_MODEL_NAME, compute_vision_embedding
from sold_item_finder.core.ai.vision_embeddings_store import VisionEmbeddingsStore
from sold_item_finder.core.ai.embeddings_store import EmbeddingsStore
from sold_item_finder.core.ai.openai_client import OpenAIClient, OpenAIUnavailableError
from sold_item_finder.core.db import Database


@dataclass(slots=True)
class SearchHit:
    file_id: str
    title: str
    sku: str
    platform: str
    listing_id: str
    notes: str
    path: str
    image_path: str
    score: float


@dataclass(slots=True)
class SemanticImageSearchResult:
    description: str
    hits: list[SearchHit]


class SemanticSearchService:
    def __init__(
        self,
        db: Database,
        embeddings_store: EmbeddingsStore,
        vision_embeddings_store: VisionEmbeddingsStore,
        ai_client: OpenAIClient | None,
        embedding_model: str = "text-embedding-3-small",
        vision_model: str = VISION_MODEL_NAME,
    ) -> None:
        self.db = db
        self.store = embeddings_store
        self.vision_store = vision_embeddings_store
        self.ai_client = ai_client
        self.embedding_model = embedding_model
        self.vision_model = vision_model

    @property
    def enabled(self) -> bool:
        return bool(self.ai_client and self.ai_client.enabled)

    def semantic_search_by_text(self, query: str, top_k: int = 25) -> list[SearchHit]:
        if not self.enabled:
            raise OpenAIUnavailableError("Semantic search is disabled")
        assert self.ai_client is not None
        query_embedding = self.ai_client.get_text_embedding(query, model=self.embedding_model)
        scored = self.rerank_candidates_by_embeddings(query_embedding, None)
        file_ids = [file_id for file_id, _ in scored[:top_k]]
        score_by_id = {file_id: score for file_id, score in scored[:top_k]}
        rows = self.db.get_items_by_file_ids(file_ids)
        results = []
        for row in rows:
            file_id = row["file_id"]
            results.append(
                SearchHit(
                    file_id=file_id,
                    title=row["title"] or Path(row["path"]).name,
                    sku=row["sku"] or "",
                    platform=row["platform"] or "unknown",
                    listing_id=row["listing_id"] or "",
                    notes=row["notes"] or "",
                    path=row["path"],
                    image_path=row["image_path"],
                    score=score_by_id.get(file_id, 0.0),
                )
            )
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def semantic_search_by_image(self, image_path: str, top_k: int = 25) -> SemanticImageSearchResult:
        # Kept for compatibility: still returns gpt-4o description and text-semantic results.
        if not self.enabled:
            raise OpenAIUnavailableError("Semantic image search is disabled")
        assert self.ai_client is not None
        description = self.ai_client.describe_image(image_path, model="gpt-4o")
        hits = self.semantic_search_by_text(description, top_k=top_k)
        return SemanticImageSearchResult(description=description, hits=hits)

    def describe_image_for_ui(self, image_path: str) -> str:
        if not self.enabled or not self.ai_client:
            return ""
        try:
            return self.ai_client.describe_image(image_path, model="gpt-4o")
        except Exception:
            return ""

    def vision_similarity_scores(
        self,
        query_image_path: str,
        candidate_file_ids: set[str],
    ) -> dict[str, float]:
        if not candidate_file_ids:
            return {}
        query = np.asarray(compute_vision_embedding(Path(query_image_path)), dtype=np.float32)
        q_norm = np.linalg.norm(query)
        if q_norm == 0:
            return {}
        vectors = self.vision_store.fetch_by_file_ids(self.vision_model, candidate_file_ids)
        scores: dict[str, float] = {}
        for file_id, vec in vectors.items():
            cand = np.asarray(vec, dtype=np.float32)
            denom = q_norm * np.linalg.norm(cand)
            if denom == 0:
                continue
            scores[file_id] = float(np.dot(query, cand) / denom)
        return scores

    def rerank_candidates_by_embeddings(
        self,
        query_embedding: list[float],
        candidate_file_ids: set[str] | None,
    ) -> list[tuple[str, float]]:
        query = np.asarray(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(query)
        if q_norm == 0:
            return []
        scores: list[tuple[str, float]] = []
        for file_id, vector in self.store.fetch_candidates_with_embeddings(self.embedding_model):
            if candidate_file_ids is not None and file_id not in candidate_file_ids:
                continue
            candidate = np.asarray(vector, dtype=np.float32)
            denom = q_norm * np.linalg.norm(candidate)
            if denom == 0:
                continue
            score = float(np.dot(query, candidate) / denom)
            scores.append((file_id, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores
