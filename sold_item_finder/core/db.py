from __future__ import annotations

import sqlite3
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class ItemRecord:
    file_id: str
    path: str
    filename: str
    platform: str
    title: str
    sku: str
    listing_id: str
    notes: str
    raw_text: str
    image_path: str
    image_hash: str
    sha256: str


class Database:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                file_id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                filename TEXT NOT NULL,
                platform TEXT,
                title TEXT,
                sku TEXT,
                listing_id TEXT,
                notes TEXT,
                raw_text TEXT,
                image_path TEXT NOT NULL,
                image_hash TEXT,
                sha256 TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._migrate_items_table()
        self.conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
                file_id UNINDEXED,
                path,
                filename,
                platform,
                title,
                sku,
                listing_id,
                notes,
                raw_text
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_items_path ON items(path)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_items_sha256 ON items(sha256)")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                file_id TEXT NOT NULL,
                model TEXT NOT NULL,
                vector BLOB NOT NULL,
                dims INTEGER NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(file_id, model)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vision_embeddings (
                file_id TEXT NOT NULL,
                model TEXT NOT NULL,
                vector BLOB NOT NULL,
                dims INTEGER NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(file_id, model)
            )
            """
        )
        self.conn.commit()

    def _migrate_items_table(self) -> None:
        cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(items)").fetchall()}
        if "image_hash" not in cols:
            self.conn.execute("ALTER TABLE items ADD COLUMN image_hash TEXT")
        if "sha256" not in cols:
            self.conn.execute("ALTER TABLE items ADD COLUMN sha256 TEXT")

    def upsert_item(self, item: ItemRecord) -> None:
        self.conn.execute(
            """
            INSERT INTO items(file_id, path, filename, platform, title, sku, listing_id, notes, raw_text, image_path, image_hash, sha256)
            VALUES(:file_id, :path, :filename, :platform, :title, :sku, :listing_id, :notes, :raw_text, :image_path, :image_hash, :sha256)
            ON CONFLICT(file_id) DO UPDATE SET
                path=excluded.path,
                filename=excluded.filename,
                platform=excluded.platform,
                title=excluded.title,
                sku=excluded.sku,
                listing_id=excluded.listing_id,
                notes=excluded.notes,
                raw_text=excluded.raw_text,
                image_path=excluded.image_path,
                image_hash=excluded.image_hash,
                sha256=excluded.sha256,
                updated_at=CURRENT_TIMESTAMP
            """,
            asdict(item),
        )
        self.conn.execute("DELETE FROM items_fts WHERE file_id = ?", (item.file_id,))
        self.conn.execute(
            """
            INSERT INTO items_fts(file_id, path, filename, platform, title, sku, listing_id, notes, raw_text)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.file_id,
                item.path,
                item.filename,
                item.platform,
                item.title,
                item.sku,
                item.listing_id,
                item.notes,
                item.raw_text,
            ),
        )
        self.conn.commit()

    def delete_missing(self, existing_ids: Iterable[str]) -> None:
        ids = list(existing_ids)
        if not ids:
            self.conn.execute("DELETE FROM items")
            self.conn.execute("DELETE FROM items_fts")
            self.conn.execute("DELETE FROM embeddings")
            self.conn.execute("DELETE FROM vision_embeddings")
            self.conn.commit()
            return
        placeholders = ",".join("?" for _ in ids)
        self.conn.execute(f"DELETE FROM items WHERE file_id NOT IN ({placeholders})", ids)
        self.conn.execute(f"DELETE FROM items_fts WHERE file_id NOT IN ({placeholders})", ids)
        self.conn.execute(f"DELETE FROM embeddings WHERE file_id NOT IN ({placeholders})", ids)
        self.conn.execute(f"DELETE FROM vision_embeddings WHERE file_id NOT IN ({placeholders})", ids)
        self.conn.commit()

    def search_text(self, query: str, limit: int = 50) -> list[sqlite3.Row]:
        cursor = self.conn.execute(
            """
            SELECT
                i.file_id,
                i.path,
                i.filename,
                i.platform,
                i.title,
                i.sku,
                i.listing_id,
                i.notes,
                i.raw_text,
                i.image_path,
                bm25(items_fts) AS rank,
                snippet(items_fts, 8, '[', ']', '...', 12) AS snippet
            FROM items_fts
            JOIN items i ON i.file_id = items_fts.file_id
            WHERE items_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        return list(cursor.fetchall())

    def count_items(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()
        return int(row["c"]) if row else 0

    def get_image_candidates(self) -> list[sqlite3.Row]:
        cursor = self.conn.execute(
            """
            SELECT file_id, path, filename, platform, title, sku, listing_id, notes, image_path, image_hash, sha256
            FROM items
            WHERE image_hash IS NOT NULL AND image_hash != ''
            """
        )
        return list(cursor.fetchall())

    def get_item(self, file_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM items WHERE file_id = ?", (file_id,)).fetchone()

    def get_items_by_file_ids(self, file_ids: list[str]) -> list[sqlite3.Row]:
        if not file_ids:
            return []
        placeholders = ",".join("?" for _ in file_ids)
        rows = self.conn.execute(
            f"""
            SELECT file_id, path, filename, platform, title, sku, listing_id, notes, image_path, image_hash, sha256
            FROM items
            WHERE file_id IN ({placeholders})
            """,
            file_ids,
        ).fetchall()
        by_id = {row["file_id"]: row for row in rows}
        return [by_id[file_id] for file_id in file_ids if file_id in by_id]

    def close(self) -> None:
        self.conn.close()
