from __future__ import annotations

import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
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

from sold_item_finder.core.image_search import ImageSearchResponse, ImageSearchService
from sold_item_finder.core.index_manager import IndexManager
from sold_item_finder.ui.workers import CancelToken, Worker
from sold_item_finder.ui.widgets.image_crop_dialog import CroppedPreviewDialog, ImageCropDialog


class ImageSearchTab(QWidget):
    def __init__(self, index_manager: IndexManager, image_search_service: ImageSearchService) -> None:
        super().__init__()
        self.index_manager = index_manager
        self.image_search_service = image_search_service
        self.pool = QThreadPool.globalInstance()
        self.cancel_token = CancelToken()
        self.image_match_paths: list[str] = []
        self._temp_query_images: list[str] = []

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.path_input = QLineEdit(str(Path.home() / "Library" / "CloudStorage"))
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_folder)
        row.addWidget(self.path_input)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        action_row = QHBoxLayout()
        self.index_btn = QPushButton("Index Folder")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.index_btn.clicked.connect(self._start_index)
        self.cancel_btn.clicked.connect(self._cancel)
        action_row.addWidget(self.index_btn)
        action_row.addWidget(self.cancel_btn)
        layout.addLayout(action_row)

        query_row = QHBoxLayout()
        self.query_image_input = QLineEdit()
        self.query_image_input.setPlaceholderText("Query image path...")
        query_browse_btn = QPushButton("Browse Query Image")
        query_browse_btn.clicked.connect(self._browse_query_image)
        crop_btn = QPushButton("Crop Query Image")
        crop_btn.clicked.connect(self._crop_query_image)
        self.search_image_btn = QPushButton("Search by Image")
        self.search_image_btn.clicked.connect(self._start_image_search)
        query_row.addWidget(self.query_image_input)
        query_row.addWidget(query_browse_btn)
        query_row.addWidget(crop_btn)
        query_row.addWidget(self.search_image_btn)
        layout.addLayout(query_row)

        option_row = QHBoxLayout()
        self.use_ai_checkbox = QCheckBox("Use AI semantic match")
        self.use_ai_checkbox.setChecked(self.image_search_service.semantic_service is not None)
        self.strict_exact_checkbox = QCheckBox("Strict exact match (SHA only)")
        option_row.addWidget(self.use_ai_checkbox)
        option_row.addWidget(self.strict_exact_checkbox)
        option_row.addStretch(1)
        layout.addLayout(option_row)

        semantic = self.image_search_service.semantic_service
        vision_model = semantic.vision_model if semantic else "disabled"
        explainer = "gpt-4o" if semantic else "disabled"
        self.model_info = QLabel(
            f"AI models: description={explainer}, vision-embedding={vision_model} | "
            "Matching pipeline: SHA-256 exact -> dHash visual -> vision cosine rerank"
        )
        self.model_info.setWordWrap(True)
        layout.addWidget(self.model_info)

        self.image_results = QListWidget()
        self.image_results.currentRowChanged.connect(self._show_image_match)
        layout.addWidget(self.image_results)

        open_row = QHBoxLayout()
        self.open_match_btn = QPushButton("Open Match in Finder")
        self.open_match_btn.clicked.connect(self._open_match_in_finder)
        open_row.addWidget(self.open_match_btn)
        layout.addLayout(open_row)

        self.image_detail = QTextEdit()
        self.image_detail.setReadOnly(True)
        layout.addWidget(self.image_detail)

        self.ai_desc_label = QLabel("")
        self.ai_desc_label.setWordWrap(True)
        layout.addWidget(self.ai_desc_label)

        debug_title = QLabel("Debug Scores (Top Candidate)")
        layout.addWidget(debug_title)
        debug_grid = QGridLayout()
        debug_grid.addWidget(QLabel("Mode"), 0, 0)
        debug_grid.addWidget(QLabel("Exact SHA"), 0, 2)
        debug_grid.addWidget(QLabel("pHash"), 1, 0)
        debug_grid.addWidget(QLabel("Embedding"), 1, 2)
        debug_grid.addWidget(QLabel("Final"), 2, 0)
        debug_grid.addWidget(QLabel("Path"), 2, 2)
        self.debug_mode = QLabel("-")
        self.debug_exact = QLabel("-")
        self.debug_phash = QLabel("-")
        self.debug_embed = QLabel("-")
        self.debug_final = QLabel("-")
        self.debug_path = QLabel("-")
        self.debug_path.setWordWrap(True)
        debug_grid.addWidget(self.debug_mode, 0, 1)
        debug_grid.addWidget(self.debug_exact, 0, 3)
        debug_grid.addWidget(self.debug_phash, 1, 1)
        debug_grid.addWidget(self.debug_embed, 1, 3)
        debug_grid.addWidget(self.debug_final, 2, 1)
        debug_grid.addWidget(self.debug_path, 2, 3)
        layout.addLayout(debug_grid)

        self.status = QLabel("Ready")
        layout.addWidget(self.status)

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Google Drive Synced Folder")
        if path:
            self.path_input.setText(path)

    def _start_index(self) -> None:
        root = Path(self.path_input.text().strip()).expanduser()
        self.cancel_token = CancelToken()
        self.index_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        worker = Worker(self.index_manager.index_folder, root, self.cancel_token.is_cancelled)
        worker.signals.started.connect(lambda: self.status.setText("Indexing..."))
        worker.signals.finished.connect(self._on_index_finished)
        worker.signals.error.connect(lambda e: self.status.setText(f"Indexing failed: {e}"))
        self.pool.start(worker)

    def _on_index_finished(self, indexed_count: int) -> None:
        self.index_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status.setText(f"Indexed {indexed_count} files.")

    def _cancel(self) -> None:
        self.cancel_token.cancel()
        self.status.setText("Cancel requested...")

    def _browse_query_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select query image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tiff)",
        )
        if file_path:
            self.query_image_input.setText(file_path)

    def _crop_query_image(self) -> None:
        source = Path(self.query_image_input.text().strip()).expanduser()
        if not source.exists():
            self.status.setText("Choose a query image before cropping.")
            return
        try:
            dialog = ImageCropDialog(source, self)
        except Exception as exc:
            self.status.setText(f"Crop tool failed to open: {exc}")
            return
        if dialog.exec() == dialog.DialogCode.Accepted:
            cropped = dialog.get_cropped()
            preview = CroppedPreviewDialog(cropped, self)
            if preview.exec() != preview.DialogCode.Accepted:
                self.status.setText("Cropped image preview canceled.")
                return

            temp_dir = Path(__file__).resolve().parents[3] / "temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_path = temp_dir / f"sif_crop_{int(time.time() * 1000)}.png"
            if cropped.save(str(temp_path), "PNG"):
                self._temp_query_images.append(str(temp_path))
                self.query_image_input.setText(str(temp_path))
                self.status.setText(f"Cropped image saved: {temp_path}")
            else:
                self.status.setText("Failed to save cropped query image.")

    def _start_image_search(self) -> None:
        query_path = Path(self.query_image_input.text().strip()).expanduser()
        if not query_path.exists():
            self.status.setText("Select a valid query image.")
            return
        self.cancel_token = CancelToken()
        self.search_image_btn.setEnabled(False)
        worker = Worker(
            self.image_search_service.search_by_image,
            query_path,
            self.use_ai_checkbox.isChecked(),
            self.strict_exact_checkbox.isChecked(),
            50,
            200,
            self.cancel_token.is_cancelled,
        )
        worker.signals.started.connect(lambda: self.status.setText("Searching similar images..."))
        worker.signals.finished.connect(self._on_image_search_finished)
        worker.signals.error.connect(lambda e: self.status.setText(f"Image search failed: {e}"))
        self.pool.start(worker)

    def _on_image_search_finished(self, response: ImageSearchResponse) -> None:
        self.search_image_btn.setEnabled(True)
        self.image_results.clear()
        self.image_match_paths = []
        for hit in response.hits:
            self.image_results.addItem(
                QListWidgetItem(
                    f"{hit.title} | {hit.platform} | score {hit.final_score:.4f} | {hit.path}"
                )
            )
            self.image_match_paths.append(hit.path)
        self.image_results.setProperty("result_payloads", response.hits)
        if response.used_ai and response.ai_description:
            self.ai_desc_label.setText(f"AI description: {response.ai_description}")
        else:
            self.ai_desc_label.setText("")
        self._update_debug_scores(response)
        status = f"Found {len(response.hits)} image matches"
        if response.warning:
            status = f"{status} | {response.warning}"
        self.status.setText(status)
        if response.hits:
            self.image_results.setCurrentRow(0)

    def _show_image_match(self, idx: int) -> None:
        results = self.image_results.property("result_payloads") or []
        if idx < 0 or idx >= len(results):
            return
        hit = results[idx]
        self.image_detail.setPlainText(
            f"Title: {hit.title}\n"
            f"SKU: {hit.sku}\n"
            f"Platform: {hit.platform}\n"
            f"Listing ID: {hit.listing_id}\n"
            f"Path: {hit.path}\n"
            f"Image: {hit.image_path}\n"
            f"Final score: {hit.final_score:.4f}\n"
            f"pHash score: {hit.phash_score:.4f}\n"
            f"Embedding score: {hit.embedding_score:.4f}\n"
            f"Exact SHA-256 match: {hit.is_exact_sha}\n"
            f"Notes: {hit.notes}\n"
        )

    def _update_debug_scores(self, response: ImageSearchResponse) -> None:
        mode = "AI + visual" if response.used_ai else "visual only"
        self.debug_mode.setText(mode)
        if not response.hits:
            self.debug_exact.setText("-")
            self.debug_phash.setText("-")
            self.debug_embed.setText("-")
            self.debug_final.setText("-")
            self.debug_path.setText("-")
            return
        top = response.hits[0]
        self.debug_exact.setText(str(top.is_exact_sha))
        self.debug_phash.setText(f"{top.phash_score:.4f}")
        self.debug_embed.setText(f"{top.embedding_score:.4f}")
        self.debug_final.setText(f"{top.final_score:.4f}")
        self.debug_path.setText(top.path)

    def _open_match_in_finder(self) -> None:
        idx = self.image_results.currentRow()
        if idx < 0 or idx >= len(self.image_match_paths):
            self.status.setText("Select a match first.")
            return
        subprocess.run(["open", self.image_match_paths[idx]], check=False)
