from pathlib import Path

from PIL import Image

from sold_item_finder.core.ai.embeddings_store import EmbeddingsStore
from sold_item_finder.core.ai.openai_client import OpenAIClient
from sold_item_finder.core.ai.semantic_search import SemanticSearchService
from sold_item_finder.core.ai.vision_embeddings_store import VisionEmbeddingsStore
from sold_item_finder.core.db import Database, ItemRecord
from sold_item_finder.core.hasher import phash, sha256_file
from sold_item_finder.core.image_search import ImageSearchService


def test_missing_openai_key_falls_back_without_crash(tmp_path: Path):
    img = tmp_path / "item.png"
    Image.new("RGB", (20, 20), color="blue").save(img)

    db = Database(tmp_path / "fallback.db")
    db.upsert_item(
        ItemRecord(
            file_id="x1",
            path=str(tmp_path),
            filename=img.name,
            platform="etsy",
            title="Blue item",
            sku="",
            listing_id="",
            notes="",
            raw_text="",
            image_path=str(img),
            image_hash=phash(img),
            sha256=sha256_file(img),
        )
    )
    semantic = SemanticSearchService(
        db,
        EmbeddingsStore(db.conn),
        VisionEmbeddingsStore(db.conn),
        ai_client=OpenAIClient(api_key=""),
        embedding_model="text-embedding-3-small",
    )
    service = ImageSearchService(db, semantic_service=semantic)
    response = service.search_by_image(img, use_ai_semantic=True)
    db.close()

    assert response.hits
    assert response.used_ai is False
