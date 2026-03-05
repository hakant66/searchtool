from pathlib import Path

from sold_item_finder.core.db import Database, ItemRecord
from sold_item_finder.core.text_search import TextSearchScopes, TextSearchService


def test_fts_search_returns_matches(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    db.upsert_item(
        ItemRecord(
            file_id="1",
            path="/tmp/item1",
            filename="blue_jacket.jpg",
            platform="etsy",
            title="Blue Denim Jacket",
            sku="SKU-1",
            listing_id="L-1",
            notes="vintage size m",
            raw_text="csv payload sold item blue",
            image_path="/tmp/item1/blue_jacket.jpg",
            image_hash="abcdef0123456789",
            sha256="deadbeef",
        )
    )
    svc = TextSearchService(db)
    results = svc.search("blue jacket", TextSearchScopes())
    db.close()
    assert results
    assert results[0].title.lower().startswith("blue")
