from pathlib import Path

from PIL import Image

from sold_item_finder.core.db import Database
from sold_item_finder.core.index_manager import IndexManager


def test_index_refresh(tmp_path: Path):
    folder = tmp_path / "drive"
    folder.mkdir()
    img = folder / "a.jpg"
    Image.new("RGB", (10, 10), color="blue").save(img)
    db = Database(tmp_path / "index.db")
    manager = IndexManager(db)
    indexed = manager.index_folder(folder)
    assert indexed == 1
    assert db.count_items() == 1
    db.close()
