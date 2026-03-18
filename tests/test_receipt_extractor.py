from __future__ import annotations

from webapp.receipt_extractor import (
    _build_openai_content_parts,
    _build_receipt_items_prompt,
    _build_receipt_summary_prompt,
    _match_item_images,
)


def test_match_item_images_uses_text_anchors():
    items = [
        {"item_name": "Vintage Drop Earrings"},
        {"item_name": "Moon Design Ladies Earrings"},
        {"item_name": "Unmatched Name"},
    ]
    text_lines = [
        {"page": 0, "text": "A Pair of Stylish Vintage Drop Earrings", "x0": 220.0, "y0": 100.0, "x1": 700.0, "y1": 120.0},
        {"page": 0, "text": "Retro Elegant ... Moon Design Ladies Earrings", "x0": 220.0, "y0": 220.0, "x1": 700.0, "y1": 240.0},
    ]
    candidate_images = [
        {"page": 0, "x0": 20.0, "y0": 90.0, "x1": 180.0, "y1": 190.0, "blob": b"img-1", "mime": "image/png"},
        {"page": 0, "x0": 20.0, "y0": 210.0, "x1": 180.0, "y1": 310.0, "blob": b"img-2", "mime": "image/png"},
        {"page": 0, "x0": 20.0, "y0": 330.0, "x1": 180.0, "y1": 430.0, "blob": b"img-3", "mime": "image/png"},
    ]

    assigned = _match_item_images(
        items=items,
        candidate_images=candidate_images,
        text_lines=text_lines,
        fallback_image=b"fallback",
    )

    assert assigned == [b"img-1", b"img-2", b"img-3"]


def test_match_item_images_falls_back_when_no_images():
    assigned = _match_item_images(
        items=[{"item_name": "Any"}],
        candidate_images=[],
        text_lines=[],
        fallback_image=b"fallback",
    )
    assert assigned == [b"fallback"]


def test_build_openai_content_parts_supports_image_only_pdf():
    content_parts, first_image = _build_openai_content_parts(
        filename="receipt.pdf",
        extracted_text="",
        vision_images=[
            {"blob": b"img-1", "mime": "image/png"},
            {"blob": b"img-2", "mime": "image/jpeg"},
        ],
    )

    assert "no extractable text layer" in content_parts[0]["text"].lower()
    assert [part["type"] for part in content_parts] == ["input_text", "input_image", "input_image"]
    assert first_image == content_parts[1]["image_url"]


def test_receipt_summary_prompt_avoids_items():
    prompt = _build_receipt_summary_prompt()
    assert "do not return items" in prompt.lower()


def test_receipt_items_prompt_requests_product_cards_only():
    prompt = _build_receipt_items_prompt(page_number=2, page_count=4)
    assert "product card" in prompt.lower()
    assert "ignore headers, footers, payment method" in prompt.lower()
