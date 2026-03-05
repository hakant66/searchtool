from pathlib import Path

from PIL import Image, ImageEnhance

from sold_item_finder.core.similarity import image_visual_similarity


def test_visual_similarity_prefers_same_image(tmp_path: Path):
    base = tmp_path / "base.png"
    altered = tmp_path / "altered.png"
    different = tmp_path / "different.png"

    img = Image.new("RGB", (120, 120), color=(180, 140, 90))
    img.save(base)

    # Slightly altered image should still be close.
    brighter = ImageEnhance.Brightness(img).enhance(1.1)
    brighter.save(altered)

    Image.new("RGB", (120, 120), color=(20, 40, 220)).save(different)

    same_score = image_visual_similarity(base, base)
    altered_score = image_visual_similarity(base, altered)
    diff_score = image_visual_similarity(base, different)

    assert same_score >= altered_score >= diff_score
