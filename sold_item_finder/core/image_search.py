from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sold_item_finder.core.ai.semantic_search import SemanticSearchService
from sold_item_finder.core.db import Database
from sold_item_finder.core.hasher import phash, sha256_file
from sold_item_finder.core.similarity import hamming_distance, image_visual_similarity


@dataclass(slots=True)
class ImageSearchHit:
    file_id: str
    title: str
    sku: str
    platform: str
    listing_id: str
    notes: str
    path: str
    image_path: str
    phash_score: float
    embedding_score: float
    final_score: float
    is_exact_sha: bool = False


@dataclass(slots=True)
class ImageSearchResponse:
    hits: list[ImageSearchHit]
    ai_description: str = ""
    used_ai: bool = False
    warning: str = ""


class ImageSearchService:
    def __init__(
        self,
        db: Database,
        semantic_service: SemanticSearchService | None = None,
        phash_weight: float = 0.7,
        embedding_weight: float = 0.3,
        visual_floor_for_semantic: float = 0.55,
        low_visual_embedding_penalty: float = 0.2,
        visual_refine_top_n: int = 120,
        hash_visual_weight: float = 0.65,
        pixel_visual_weight: float = 0.35,
    ) -> None:
        self.db = db
        self.semantic_service = semantic_service
        self.phash_weight = phash_weight
        self.embedding_weight = embedding_weight
        self.visual_floor_for_semantic = visual_floor_for_semantic
        self.low_visual_embedding_penalty = low_visual_embedding_penalty
        self.visual_refine_top_n = visual_refine_top_n
        self.hash_visual_weight = hash_visual_weight
        self.pixel_visual_weight = pixel_visual_weight

    def search_by_image(
        self,
        query_path: Path,
        use_ai_semantic: bool,
        strict_exact_only: bool = False,
        top_k: int = 50,
        phash_top_n: int = 200,
        cancel_flag: callable | None = None,
    ) -> ImageSearchResponse:
        rows = self.db.get_image_candidates()
        if not rows:
            return ImageSearchResponse(hits=[])

        query_sha = sha256_file(query_path)
        exact_hits = [row for row in rows if (row["sha256"] or "") == query_sha]
        if exact_hits:
            return ImageSearchResponse(
                hits=[
                    ImageSearchHit(
                        file_id=row["file_id"],
                        title=row["title"] or row["filename"],
                        sku=row["sku"] or "",
                        platform=row["platform"] or "unknown",
                        listing_id=row["listing_id"] or "",
                        notes=row["notes"] or "",
                        path=row["path"],
                        image_path=row["image_path"],
                        phash_score=1.0,
                        embedding_score=1.0,
                        final_score=1.0,
                        is_exact_sha=True,
                    )
                    for row in exact_hits[:top_k]
                ],
                used_ai=False,
            )
        if strict_exact_only:
            return ImageSearchResponse(
                hits=[],
                used_ai=False,
                warning=(
                    "No exact SHA-256 match found. "
                    "If you used a cropped/re-encoded image, exact match is unlikely."
                ),
            )

        query_hash = phash(query_path)
        phash_ranked: list[tuple[float, dict]] = []
        for row in rows:
            if cancel_flag and cancel_flag():
                break
            candidate_hash = row["image_hash"] or ""
            if not candidate_hash:
                continue
            dist = hamming_distance(query_hash, candidate_hash)
            max_bits = max(4 * len(query_hash), 4 * len(candidate_hash), 1)
            score = 1.0 - (dist / max_bits)
            phash_ranked.append((score, dict(row)))
        phash_ranked.sort(key=lambda x: x[0], reverse=True)
        phash_top = phash_ranked[:phash_top_n]
        refined_visual = self._refine_visual_scores(query_path, phash_top)

        ai_description = ""
        embed_scores: dict[str, float] = {}
        used_ai = False
        if use_ai_semantic and self.semantic_service:
            candidate_ids = {row["file_id"] for _, row in phash_top}
            embed_scores = self.semantic_service.vision_similarity_scores(str(query_path), candidate_ids)
            ai_description = self.semantic_service.describe_image_for_ui(str(query_path))
            used_ai = bool(embed_scores)

        blended: list[ImageSearchHit] = []
        for _, row in phash_top:
            file_id = row["file_id"]
            phash_score = refined_visual.get(file_id, 0.0)
            emb_score = embed_scores.get(file_id, 0.0)
            if used_ai and phash_score < self.visual_floor_for_semantic:
                emb_score *= self.low_visual_embedding_penalty
            final_score = (
                (self.phash_weight * phash_score) + (self.embedding_weight * emb_score)
                if used_ai
                else phash_score
            )
            blended.append(
                ImageSearchHit(
                    file_id=file_id,
                    title=row["title"] or row["filename"],
                    sku=row["sku"] or "",
                    platform=row["platform"] or "unknown",
                    listing_id=row["listing_id"] or "",
                    notes=row["notes"] or "",
                    path=row["path"],
                    image_path=row["image_path"],
                    phash_score=phash_score,
                    embedding_score=emb_score,
                    final_score=final_score,
                )
            )
        blended.sort(key=lambda x: x.final_score, reverse=True)
        warning = ""
        if blended and blended[0].final_score < 0.55:
            warning = (
                "Top visual similarity is low. Try a tighter crop around unique details, "
                "or use the original file for exact SHA matching."
            )
        return ImageSearchResponse(
            hits=blended[:top_k],
            ai_description=ai_description,
            used_ai=used_ai,
            warning=warning,
        )

    def _refine_visual_scores(
        self,
        query_path: Path,
        phash_top: list[tuple[float, dict]],
    ) -> dict[str, float]:
        refined: dict[str, float] = {}
        for idx, (hash_score, row) in enumerate(phash_top):
            file_id = row["file_id"]
            if idx >= self.visual_refine_top_n:
                refined[file_id] = hash_score
                continue
            pixel_score = image_visual_similarity(query_path, Path(row["image_path"]))
            refined[file_id] = (
                self.hash_visual_weight * hash_score
                + self.pixel_visual_weight * pixel_score
            )
        return refined
