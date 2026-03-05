from pathlib import Path

from PIL import Image

from sold_item_finder.core.email.models import EmailMessage
from sold_item_finder.core.report_writer import ReportWriter
from sold_item_finder.core.text_search import TextSearchResult


def test_report_writer_creates_docx(tmp_path: Path):
    image_path = tmp_path / "thumb.png"
    Image.new("RGB", (50, 50), color="red").save(image_path)
    writer = ReportWriter(base_dir=tmp_path / "reports")
    message = EmailMessage(
        message_id="abc123",
        date="Wed, 04 Mar 2026 12:00:00 +0000",
        from_address="seller@example.com",
        to_address="taskin.baba@gmail.com",
        subject="Sold: Blue Jacket",
        snippet="snippet",
        raw_headers="headers",
    )
    results = [
        TextSearchResult(
            file_id="1",
            title="Blue Jacket",
            sku="S1",
            platform="etsy",
            listing_id="L1",
            notes="note",
            path="/tmp/item",
            image_paths=[str(image_path)],
            score=0.88,
            snippet="snip",
        )
    ]
    out = writer.write_email_report(message, "blue jacket", results, "test-v1")
    assert out.exists()
    assert out.suffix == ".docx"
