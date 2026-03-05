from pathlib import Path

from sold_item_finder.core.ai.embeddings_store import EmbeddingsStore
from sold_item_finder.core.ai.semantic_search import SemanticSearchService
from sold_item_finder.core.ai.vision_embeddings_store import VisionEmbeddingsStore
from sold_item_finder.core.db import Database


def test_cosine_similarity_ranking_is_deterministic(tmp_path: Path):
    db = Database(tmp_path / "semantic.db")
    store = EmbeddingsStore(db.conn)
    vision_store = VisionEmbeddingsStore(db.conn)
    store.upsert_embedding("a", "text-embedding-3-small", [1.0, 0.0, 0.0])
    store.upsert_embedding("b", "text-embedding-3-small", [0.7, 0.7, 0.0])
    store.upsert_embedding("c", "text-embedding-3-small", [0.0, 1.0, 0.0])
    svc = SemanticSearchService(
        db,
        store,
        vision_store,
        ai_client=None,
        embedding_model="text-embedding-3-small",
    )

    ranked = svc.rerank_candidates_by_embeddings([1.0, 0.0, 0.0], {"a", "b", "c"})
    order = [file_id for file_id, _ in ranked]
    db.close()
    assert order[:3] == ["a", "b", "c"]
