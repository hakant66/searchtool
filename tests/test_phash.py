from pathlib import Path

from PIL import Image

from sold_item_finder.core.hasher import phash


def test_phash_is_stable(tmp_path: Path):
    p = tmp_path / "x.png"
    Image.new("RGB", (24, 24), color="green").save(p)
    value = phash(p)
    assert value == phash(p)
    assert len(value) == 64
