from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import hashlib
from pathlib import Path

from sold_item_finder.core.ai.embeddings_store import EmbeddingsStore
from sold_item_finder.core.ai.item_text import build_item_text
from sold_item_finder.core.ai.openai_client import OpenAIClient
from sold_item_finder.core.ai.vision_embedding import VISION_MODEL_NAME, compute_vision_embedding
from sold_item_finder.core.ai.vision_embeddings_store import VisionEmbeddingsStore
from sold_item_finder.core.db import Database, ItemRecord
from sold_item_finder.core.hasher import phash, sha256_file
from sold_item_finder.core.metadata_resolver import MetadataResolver
from sold_item_finder.core.scanner import iter_image_files


class IndexManager:
    def __init__(
        self,
        db: Database,
        resolver: MetadataResolver | None = None,
        ai_client: OpenAIClient | None = None,
        embeddings_store: EmbeddingsStore | None = None,
        vision_embeddings_store: VisionEmbeddingsStore | None = None,
        embedding_model: str = "text-embedding-3-small",
        vision_embedding_model: str = VISION_MODEL_NAME,
        enable_openai_embeddings: bool | None = None,
    ) -> None:
        self.db = db
        self.resolver = resolver or MetadataResolver()
        self.ai_client = ai_client
        self.embeddings_store = embeddings_store
        self.vision_embeddings_store = vision_embeddings_store
        self.embedding_model = embedding_model
        self.vision_embedding_model = vision_embedding_model
        default_enabled = bool(os.getenv("OPENAI_API_KEY"))
        if enable_openai_embeddings is None:
            self.enable_openai_embeddings = default_enabled and bool(ai_client and ai_client.enabled)
        else:
            self.enable_openai_embeddings = enable_openai_embeddings

    def index_folder(self, root: Path, cancel_flag: callable | None = None) -> int:
        indexed = 0
        seen_ids: list[str] = []
        embedding_tasks: list[tuple[str, str]] = []
        for image_path in iter_image_files(root):
            if cancel_flag and cancel_flag():
                break
            meta = self.resolver.resolve_for_image(image_path)
            file_id = self._file_id(image_path)
            seen_ids.append(file_id)
            previous = self.db.get_item(file_id)
            record = ItemRecord(
                file_id=file_id,
                path=str(image_path.parent),
                filename=image_path.name,
                platform=meta.get("platform", ""),
                title=meta.get("title", ""),
                sku=meta.get("sku", ""),
                listing_id=meta.get("listing_id", ""),
                notes=meta.get("notes", ""),
                raw_text=meta.get("raw_text", ""),
                image_path=str(image_path),
                image_hash=phash(image_path),
                sha256=sha256_file(image_path),
            )
            self.db.upsert_item(record)
            self._upsert_vision_embedding(previous, record)
            if self._should_refresh_embedding(previous, record):
                meta_dict = {
                    "title": record.title,
                    "platform": record.platform,
                    "sku": record.sku,
                    "listing_id": record.listing_id,
                    "notes": record.notes,
                }
                embedding_tasks.append((record.file_id, build_item_text(meta_dict, record.path, record.filename)))
            indexed += 1
        self._compute_embeddings(embedding_tasks, cancel_flag)
        self.db.delete_missing(seen_ids)
        return indexed

    def _upsert_vision_embedding(self, previous, record: ItemRecord) -> None:
        if not self.vision_embeddings_store:
            return
        if previous is None:
            should_refresh = True
        else:
            should_refresh = any(
                previous[field] != getattr(record, field)
                for field in ["path", "filename", "sha256"]
            )
        if not should_refresh:
            existing = self.vision_embeddings_store.get_embedding(record.file_id, self.vision_embedding_model)
            should_refresh = existing is None
        if not should_refresh:
            return
        try:
            vector = compute_vision_embedding(Path(record.image_path))
        except Exception:
            return
        self.vision_embeddings_store.upsert_embedding(record.file_id, self.vision_embedding_model, vector)

    def _should_refresh_embedding(self, previous, record: ItemRecord) -> bool:
        if not (self.enable_openai_embeddings and self.embeddings_store and self.ai_client and self.ai_client.enabled):
            return False
        if previous is None:
            return True
        changed = any(
            previous[field] != getattr(record, field)
            for field in ["path", "filename", "platform", "title", "sku", "listing_id", "notes", "raw_text", "sha256"]
        )
        if changed:
            return True
        existing = self.embeddings_store.get_embedding(record.file_id, self.embedding_model)
        return existing is None

    def _compute_embeddings(
        self,
        tasks: list[tuple[str, str]],
        cancel_flag: callable | None = None,
    ) -> None:
        if not tasks or not self.embeddings_store or not self.ai_client or not self.ai_client.enabled:
            return
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self.ai_client.get_text_embedding, text, self.embedding_model): file_id
                for file_id, text in tasks
            }
            for future in as_completed(futures):
                if cancel_flag and cancel_flag():
                    break
                file_id = futures[future]
                try:
                    vector = future.result()
                except Exception:
                    continue
                self.embeddings_store.upsert_embedding(file_id, self.embedding_model, vector)

    @staticmethod
    def _file_id(path: Path) -> str:
        st = path.stat()
        payload = f"{path.resolve()}::{st.st_size}::{st.st_mtime_ns}".encode("utf-8")
        return hashlib.sha1(payload).hexdigest()
