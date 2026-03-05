from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from sold_item_finder.core.ai.openai_client import OpenAIUnavailableError
from sold_item_finder.core.ai.semantic_search import SemanticSearchService
from sold_item_finder.core.text_search import TextSearchResult, TextSearchScopes, TextSearchService
from sold_item_finder.ui.workers import Worker


class TextSearchTab(QWidget):
    def __init__(
        self,
        text_service: TextSearchService,
        semantic_service: SemanticSearchService | None = None,
    ) -> None:
        super().__init__()
        self.text_service = text_service
        self.semantic_service = semantic_service
        self.pool = QThreadPool.globalInstance()
        self.current_results: list[TextSearchResult] = []

        layout = QVBoxLayout(self)
        query_row = QHBoxLayout()
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Search text...")
        self.search_btn = QPushButton("Search Text")
        self.clear_btn = QPushButton("Clear")
        self.search_btn.clicked.connect(self._search)
        self.clear_btn.clicked.connect(self._clear)
        query_row.addWidget(self.query_input)
        query_row.addWidget(self.search_btn)
        query_row.addWidget(self.clear_btn)
        layout.addLayout(query_row)

        mode_row = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Keyword (FTS)", "Semantic (AI)"])
        mode_row.addWidget(QLabel("Search mode:"))
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)
        semantic_model = (
            self.semantic_service.embedding_model
            if self.semantic_service is not None
            else "disabled"
        )
        self.model_info = QLabel(
            f"Keyword mode uses SQLite FTS5 | Semantic mode uses embedding model: {semantic_model}"
        )
        self.model_info.setWordWrap(True)
        layout.addWidget(self.model_info)

        scope_row = QHBoxLayout()
        self.scope_path = QCheckBox("Filenames/paths")
        self.scope_path.setChecked(True)
        self.scope_meta = QCheckBox("Metadata fields")
        self.scope_meta.setChecked(True)
        self.scope_raw = QCheckBox("Parsed JSON/CSV values")
        self.scope_raw.setChecked(True)
        scope_row.addWidget(self.scope_path)
        scope_row.addWidget(self.scope_meta)
        scope_row.addWidget(self.scope_raw)
        layout.addLayout(scope_row)

        body = QHBoxLayout()
        self.results_list = QListWidget()
        self.results_list.currentRowChanged.connect(self._show_selected)
        body.addWidget(self.results_list, 2)

        right = QVBoxLayout()
        self.meta_box = QTextEdit()
        self.meta_box.setReadOnly(True)
        thumbs = QHBoxLayout()
        self.thumb_labels = [QLabel("No image"), QLabel("No image"), QLabel("No image")]
        for label in self.thumb_labels:
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFixedSize(180, 180)
            thumbs.addWidget(label)
        right.addWidget(self.meta_box)
        right.addLayout(thumbs)
        body.addLayout(right, 3)
        layout.addLayout(body)

        self.status = QLabel("Ready")
        layout.addWidget(self.status)

    def _build_scopes(self) -> TextSearchScopes:
        return TextSearchScopes(
            path_and_filename=self.scope_path.isChecked(),
            metadata_fields=self.scope_meta.isChecked(),
            raw_structured_text=self.scope_raw.isChecked(),
        )

    def _search(self) -> None:
        query = self.query_input.text().strip()
        if not query:
            self.status.setText("Enter search text.")
            return
        self.search_btn.setEnabled(False)
        if self.mode_combo.currentText().startswith("Semantic"):
            worker = Worker(self._search_semantic, query)
        else:
            worker = Worker(self.text_service.search, query, self._build_scopes())
        worker.signals.started.connect(lambda: self.status.setText("Searching..."))
        worker.signals.finished.connect(self._search_finished)
        worker.signals.error.connect(lambda e: self.status.setText(f"Search failed: {e}"))
        self.pool.start(worker)

    def _search_semantic(self, query: str) -> list[TextSearchResult]:
        if not self.semantic_service:
            raise OpenAIUnavailableError("Semantic service is unavailable")
        try:
            hits = self.semantic_service.semantic_search_by_text(query, top_k=50)
        except OpenAIUnavailableError:
            return self.text_service.search(query, self._build_scopes(), limit=50)
        return [
            TextSearchResult(
                file_id=hit.file_id,
                title=hit.title,
                sku=hit.sku,
                platform=hit.platform,
                listing_id=hit.listing_id,
                notes=hit.notes,
                path=hit.path,
                image_paths=[hit.image_path],
                score=hit.score,
                snippet="semantic match",
            )
            for hit in hits
        ]

    def _search_finished(self, results: list[TextSearchResult]) -> None:
        self.search_btn.setEnabled(True)
        self.current_results = results
        self.results_list.clear()
        for result in results:
            title = result.title or "(untitled)"
            sku = f" | SKU: {result.sku}" if result.sku else ""
            item = QListWidgetItem(f"{title}{sku} | {result.platform} | score {result.score:.4f}")
            self.results_list.addItem(item)
        self.status.setText(f"Found {len(results)} results")
        if results:
            self.results_list.setCurrentRow(0)

    def _show_selected(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.current_results):
            return
        result = self.current_results[idx]
        self.meta_box.setPlainText(
            f"Title: {result.title}\n"
            f"SKU: {result.sku}\n"
            f"Platform: {result.platform}\n"
            f"Listing ID: {result.listing_id}\n"
            f"Notes: {result.notes}\n"
            f"Path: {result.path}\n"
            f"Snippet: {result.snippet}\n"
        )
        for i, label in enumerate(self.thumb_labels):
            label.setText("No image")
            label.setPixmap(QPixmap())
            if i < len(result.image_paths):
                image_path = Path(result.image_paths[i])
                pix = QPixmap(str(image_path))
                if not pix.isNull():
                    label.setPixmap(pix.scaled(170, 170, Qt.AspectRatioMode.KeepAspectRatio))
                else:
                    label.setText(image_path.name)

    def _clear(self) -> None:
        self.query_input.clear()
        self.results_list.clear()
        self.meta_box.clear()
        self.current_results = []
        for label in self.thumb_labels:
            label.setText("No image")
            label.setPixmap(QPixmap())
        self.status.setText("Cleared")
