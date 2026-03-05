from __future__ import annotations

from PySide6.QtCore import QSettings, QThreadPool
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from sold_item_finder.core.ai.openai_client import OpenAIClient
from sold_item_finder.core.index_manager import IndexManager
from sold_item_finder.ui.workers import Worker


class SettingsTab(QWidget):
    def __init__(self, index_manager: IndexManager, ai_available: bool) -> None:
        super().__init__()
        self.index_manager = index_manager
        self.ai_available = ai_available
        self.pool = QThreadPool.globalInstance()
        self.settings = QSettings("SoldItemFinder", "SoldItemFinder")

        layout = QVBoxLayout(self)
        self.embeddings_checkbox = QCheckBox("Enable OpenAI embedding generation during indexing")
        self.embeddings_checkbox.setChecked(self.index_manager.enable_openai_embeddings)
        layout.addWidget(self.embeddings_checkbox)

        self.ai_status = QLabel(
            "OpenAI status: enabled (API key detected)"
            if ai_available
            else "OpenAI status: unavailable (missing key or SDK)"
        )
        layout.addWidget(self.ai_status)
        self._set_ai_status_label()

        row = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        self.test_btn = QPushButton("Test OpenAI Connection")
        apply_btn.clicked.connect(self._apply)
        self.test_btn.clicked.connect(self._test_connection)
        row.addStretch(1)
        row.addWidget(self.test_btn)
        row.addWidget(apply_btn)
        layout.addLayout(row)

        self.status = QLabel("Ready")
        layout.addWidget(self.status)
        layout.addStretch(1)

    def _set_ai_status_label(self) -> None:
        self.ai_status.setText(
            "OpenAI status: enabled (key + SDK + API reachable)"
            if self.ai_available
            else "OpenAI status: unavailable (missing key, SDK, or API unreachable)"
        )

    def _test_connection(self) -> None:
        self.test_btn.setEnabled(False)
        worker = Worker(self._test_connection_task)
        worker.signals.started.connect(lambda: self.status.setText("Testing OpenAI connection..."))
        worker.signals.finished.connect(self._on_test_success)
        worker.signals.error.connect(self._on_test_error)
        self.pool.start(worker)

    def _test_connection_task(self) -> str:
        client = OpenAIClient()
        if not client.enabled:
            raise RuntimeError("OpenAI unavailable. Set OPENAI_API_KEY and ensure openai is installed.")
        vector = client.get_text_embedding("sold item finder connection test", "text-embedding-3-small")
        if not vector:
            raise RuntimeError("OpenAI test failed: empty embedding response.")
        return f"Connection successful. Received embedding dimensions: {len(vector)}"

    def _on_test_success(self, message: str) -> None:
        self.test_btn.setEnabled(True)
        self.ai_available = True
        self._set_ai_status_label()
        self.status.setText(message)

    def _on_test_error(self, error: str) -> None:
        self.test_btn.setEnabled(True)
        self.ai_available = False
        self._set_ai_status_label()
        self.status.setText(f"OpenAI test failed: {error}")

    def _apply(self) -> None:
        enabled = self.embeddings_checkbox.isChecked()
        if enabled and not self.ai_available:
            self.index_manager.enable_openai_embeddings = False
            self.embeddings_checkbox.setChecked(False)
            self.settings.setValue("enable_openai_embeddings", False)
            self.status.setText("Cannot enable: OpenAI is unavailable in this session.")
            return
        self.index_manager.enable_openai_embeddings = enabled
        self.settings.setValue("enable_openai_embeddings", enabled)
        self.status.setText(
            "OpenAI embedding generation enabled for future indexing runs."
            if enabled
            else "OpenAI embedding generation disabled."
        )
