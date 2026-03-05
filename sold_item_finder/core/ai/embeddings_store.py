from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator

import numpy as np


class EmbeddingsStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._init_schema()

    def _init_schema(self) -> None:
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
        self.conn.commit()

    def upsert_embedding(self, file_id: str, model: str, vector: list[float]) -> None:
        arr = np.asarray(vector, dtype=np.float32)
        self.conn.execute(
            """
            INSERT INTO embeddings(file_id, model, vector, dims, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(file_id, model) DO UPDATE SET
                vector=excluded.vector,
                dims=excluded.dims,
                updated_at=excluded.updated_at
            """,
            (file_id, model, arr.tobytes(), int(arr.shape[0]), time.time()),
        )
        self.conn.commit()

    def get_embedding(self, file_id: str, model: str) -> list[float] | None:
        row = self.conn.execute(
            "SELECT vector, dims FROM embeddings WHERE file_id = ? AND model = ?",
            (file_id, model),
        ).fetchone()
        if not row:
            return None
        arr = np.frombuffer(row["vector"], dtype=np.float32, count=row["dims"])
        return arr.tolist()

    def fetch_candidates_with_embeddings(self, model: str) -> Iterator[tuple[str, list[float]]]:
        cursor = self.conn.execute(
            "SELECT file_id, vector, dims FROM embeddings WHERE model = ?",
            (model,),
        )
        for row in cursor.fetchall():
            arr = np.frombuffer(row["vector"], dtype=np.float32, count=row["dims"])
            yield row["file_id"], arr.tolist()
