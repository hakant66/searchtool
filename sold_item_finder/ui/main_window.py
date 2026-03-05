from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sold_item_finder.core.db import Database
from sold_item_finder.core.ai.embeddings_store import EmbeddingsStore
from sold_item_finder.core.ai.openai_client import OpenAIClient
from sold_item_finder.core.ai.semantic_search import SemanticSearchService
from sold_item_finder.core.ai.vision_embeddings_store import VisionEmbeddingsStore
from sold_item_finder.core.image_search import ImageSearchService
from sold_item_finder.core.index_manager import IndexManager
from sold_item_finder.core.query_normalizer import QueryNormalizer
from sold_item_finder.core.report_writer import ReportWriter
from sold_item_finder.core.text_search import TextSearchService
from sold_item_finder.ui.tabs.email_conn_tab import EmailConnTab
from sold_item_finder.ui.tabs.image_search_tab import ImageSearchTab
from sold_item_finder.ui.tabs.settings_tab import SettingsTab
from sold_item_finder.ui.tabs.text_search_tab import TextSearchTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Sold Item Finder")
        self.resize(1200, 800)

        db_path = Path.home() / "Library" / "Application Support" / "SoldItemFinder" / "index.db"
        self.db = Database(db_path)
        self.ai_client = OpenAIClient()
        self.embeddings_store = EmbeddingsStore(self.db.conn)
        self.vision_embeddings_store = VisionEmbeddingsStore(self.db.conn)
        self.semantic_service = SemanticSearchService(
            self.db,
            self.embeddings_store,
            self.vision_embeddings_store,
            self.ai_client,
        )
        ui_settings = QSettings("SoldItemFinder", "SoldItemFinder")
        saved_toggle = ui_settings.value("enable_openai_embeddings", None)
        if saved_toggle is None:
            enable_openai_embeddings = None
        else:
            enable_openai_embeddings = str(saved_toggle).strip().lower() in {"1", "true", "yes", "on"}
        self.index_manager = IndexManager(
            self.db,
            ai_client=self.ai_client,
            embeddings_store=self.embeddings_store,
            vision_embeddings_store=self.vision_embeddings_store,
            embedding_model="text-embedding-3-small",
            enable_openai_embeddings=enable_openai_embeddings,
        )
        self.image_search_service = ImageSearchService(self.db, semantic_service=self.semantic_service)
        self.text_service = TextSearchService(self.db)
        self.query_normalizer = QueryNormalizer()
        self.report_writer = ReportWriter()

        tabs = QTabWidget()

        self.image_tab = ImageSearchTab(self.index_manager, self.image_search_service)
        self.text_tab = TextSearchTab(self.text_service, self.semantic_service)
        self.email_tab = EmailConnTab(self.text_service, self.query_normalizer, self.report_writer)
        self.settings_tab = SettingsTab(self.index_manager, ai_available=self.ai_client.enabled)

        tabs.addTab(self.image_tab, "Image Search")
        tabs.addTab(self.text_tab, "Text Search")
        tabs.addTab(self.email_tab, "Email Conn")
        tabs.addTab(self.settings_tab, "Settings")

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.addWidget(tabs)
        footer = QHBoxLayout()
        footer.addStretch(1)
        exit_btn = QPushButton("Exit")
        exit_btn.clicked.connect(self.close)
        footer.addWidget(exit_btn)
        root_layout.addLayout(footer)
        self.setCentralWidget(root)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.db.close()
        super().closeEvent(event)
