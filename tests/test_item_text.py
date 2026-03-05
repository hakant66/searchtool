from sold_item_finder.core.ai.item_text import build_item_text


def test_build_item_text_includes_key_fields():
    metadata = {
        "title": "Blue Denim Jacket",
        "platform": "etsy",
        "sku": "SKU-777",
        "listing_id": "LIST-42",
        "notes": "vintage size medium",
    }
    text = build_item_text(metadata, "/drive/sold/etsy/jackets", "blue_jacket.jpg")
    lowered = text.lower()
    assert "blue denim jacket" in lowered
    assert "etsy" in lowered
    assert "sku-777" in lowered
    assert "list-42" in lowered
    assert "jacket" in lowered
