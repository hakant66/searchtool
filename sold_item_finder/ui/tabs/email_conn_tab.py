from __future__ import annotations

from datetime import datetime
import subprocess

import keyring
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from sold_item_finder.core.email.mcp_client import EmailMcpClient
from sold_item_finder.core.email.models import EmailMessage, EmailSettings
from sold_item_finder.core.query_normalizer import QueryNormalizer
from sold_item_finder.core.report_writer import ReportWriter
from sold_item_finder.core.text_search import TextSearchScopes, TextSearchService
from sold_item_finder.ui.workers import CancelToken, Worker

KEYRING_SERVICE = "sold_item_finder_imap"


class EmailConnTab(QWidget):
    def __init__(
        self,
        text_service: TextSearchService,
        query_normalizer: QueryNormalizer,
        report_writer: ReportWriter,
    ) -> None:
        super().__init__()
        self.text_service = text_service
        self.normalizer = query_normalizer
        self.report_writer = report_writer
        self.pool = QThreadPool.globalInstance()
        self.cancel = CancelToken()
        self.messages: list[EmailMessage] = []
        self.latest_results: list = []
        self.mcp_client = EmailMcpClient()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.host_input = QLineEdit("imap.gmail.com")
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(993)
        self.username_input = QLineEdit("taskin.baba@gmail.com")
        self.target_to_input = QLineEdit("taskin.baba@gmail.com")
        self.mailbox_input = QLineEdit("INBOX")
        self.window_days = QSpinBox()
        self.window_days.setRange(1, 365)
        self.window_days.setValue(30)
        self.max_messages = QSpinBox()
        self.max_messages.setRange(1, 5000)
        self.max_messages.setValue(200)
        self.auth_method = QComboBox()
        self.auth_method.addItems(["password", "oauth2 (not implemented)"])
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.raw_subject_toggle = QCheckBox("Use raw subject")
        form.addRow("IMAP Host", self.host_input)
        form.addRow("Port", self.port_input)
        form.addRow("Username", self.username_input)
        form.addRow("Target To Address", self.target_to_input)
        form.addRow("Mailbox", self.mailbox_input)
        form.addRow("Window days", self.window_days)
        form.addRow("Max messages", self.max_messages)
        form.addRow("Auth method", self.auth_method)
        form.addRow("Password", self.password_input)
        form.addRow(self.raw_subject_toggle)
        self.enable_debug_toggle = QCheckBox("Enable debug screen")
        self.enable_debug_toggle.toggled.connect(self._toggle_debug)
        form.addRow(self.enable_debug_toggle)
        layout.addLayout(form)

        settings_actions = QHBoxLayout()
        save_pw = QPushButton("Save Password")
        test_conn = QPushButton("Test Connection")
        fetch_btn = QPushButton("Fetch Emails")
        cancel_btn = QPushButton("Cancel")
        save_pw.clicked.connect(self._save_password)
        test_conn.clicked.connect(self._test_connection)
        fetch_btn.clicked.connect(self._fetch_emails)
        cancel_btn.clicked.connect(self._cancel)
        settings_actions.addWidget(save_pw)
        settings_actions.addWidget(test_conn)
        settings_actions.addWidget(fetch_btn)
        settings_actions.addWidget(cancel_btn)
        layout.addLayout(settings_actions)

        body = QHBoxLayout()
        left = QVBoxLayout()
        self.email_list = QListWidget()
        self.email_list.currentRowChanged.connect(self._show_email_details)
        left.addWidget(QLabel("Emails"))
        left.addWidget(self.email_list)
        body.addLayout(left, 2)

        right = QVBoxLayout()
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.attachments_list = QListWidget()
        self.attachments_list.currentRowChanged.connect(self._show_attachment_details)
        self.attachment_text = QTextEdit()
        self.attachment_text.setReadOnly(True)
        self.search_results = QListWidget()
        right.addWidget(QLabel("Email details / snippet"))
        right.addWidget(self.details)
        right.addWidget(QLabel("Attachments"))
        right.addWidget(self.attachments_list)
        right.addWidget(QLabel("Attachment extracted text (PDF/DOCX/CSV/XLSX)"))
        right.addWidget(self.attachment_text)
        right.addWidget(QLabel("Associated search matches"))
        right.addWidget(self.search_results)
        process_row = QHBoxLayout()
        process_selected = QPushButton("Process Selected")
        process_all = QPushButton("Process All (Latest)")
        open_finder = QPushButton("Open in Finder")
        process_selected.clicked.connect(self._process_selected)
        process_all.clicked.connect(self._process_all)
        open_finder.clicked.connect(self._open_selected_in_finder)
        process_row.addWidget(process_selected)
        process_row.addWidget(process_all)
        process_row.addWidget(open_finder)
        right.addLayout(process_row)
        body.addLayout(right, 3)
        layout.addLayout(body)

        self.status = QLabel("Ready")
        layout.addWidget(self.status)
        self.debug_box = QTextEdit()
        self.debug_box.setReadOnly(True)
        self.debug_box.setVisible(False)
        layout.addWidget(self.debug_box)

    def _toggle_debug(self, enabled: bool) -> None:
        self.debug_box.setVisible(enabled)
        if enabled:
            self._debug("Debug screen enabled.")

    def _debug(self, message: str) -> None:
        if not self.enable_debug_toggle.isChecked():
            return
        ts = datetime.now().strftime("%H:%M:%S")
        self.debug_box.append(f"[{ts}] {message}")

    def _settings(self) -> EmailSettings:
        method = self.auth_method.currentText().split(" ")[0]
        return EmailSettings(
            host=self.host_input.text().strip(),
            port=int(self.port_input.value()),
            username=self.username_input.text().strip(),
            auth_method=method,
            target_to_address=self.target_to_input.text().strip(),
            mailbox=self.mailbox_input.text().strip() or "INBOX",
            search_window_days=int(self.window_days.value()),
            max_messages=int(self.max_messages.value()),
        )

    def _secret(self) -> str:
        username = self.username_input.text().strip()
        return keyring.get_password(KEYRING_SERVICE, username) or ""

    def _save_password(self) -> None:
        username = self.username_input.text().strip()
        pw = self.password_input.text()
        if not username or not pw:
            QMessageBox.warning(self, "Missing value", "Username and password are required.")
            return
        keyring.set_password(KEYRING_SERVICE, username, pw)
        self.password_input.clear()
        self.status.setText("Password saved in keyring.")
        self._debug(f"Saved password to keyring for user {username}.")

    def _test_connection(self) -> None:
        worker = Worker(self._connect_and_disconnect)
        worker.signals.started.connect(lambda: self.status.setText("Testing connection..."))
        worker.signals.started.connect(
            lambda: self._debug(
                f"Testing MCP email tool connection to {self.host_input.text().strip()}:{self.port_input.value()}"
            )
        )
        worker.signals.finished.connect(lambda _: self.status.setText("Connection successful."))
        worker.signals.finished.connect(lambda _: self._debug("MCP email tool test connection successful."))
        worker.signals.error.connect(lambda e: self.status.setText(f"Connection failed: {e}"))
        worker.signals.error.connect(lambda e: self._debug(f"MCP email tool test connection failed: {e}"))
        self.pool.start(worker)

    def _connect_and_disconnect(self) -> bool:
        settings = self._settings()
        if settings.auth_method != "password":
            raise RuntimeError("OAuth2 is not implemented in this build.")
        secret = self._secret()
        if not secret:
            raise RuntimeError("No password in keyring. Use Save Password first.")
        result = self.mcp_client.test_connection(settings, secret)
        if not result.get("ok"):
            raise RuntimeError(result.get("message", "Connection test failed"))
        return True

    def _fetch_emails(self) -> None:
        self.cancel = CancelToken()
        worker = Worker(self._fetch_emails_task, self.cancel.is_cancelled)
        worker.signals.started.connect(lambda: self.status.setText("Fetching emails..."))
        worker.signals.started.connect(
            lambda: self._debug(
                "Fetching emails from mailbox "
                f"{self.mailbox_input.text().strip() or 'INBOX'} "
                f"(window_days={self.window_days.value()}, max_messages={self.max_messages.value()})"
            )
        )
        worker.signals.finished.connect(self._on_fetched)
        worker.signals.error.connect(lambda e: self.status.setText(f"Fetch failed: {e}"))
        worker.signals.error.connect(lambda e: self._debug(f"Fetch failed: {e}"))
        self.pool.start(worker)

    def _fetch_emails_task(self, cancel_flag) -> list[EmailMessage]:
        _ = cancel_flag  # MCP one-shot call is not currently cancellable mid-request.
        settings = self._settings()
        if settings.auth_method != "password":
            raise RuntimeError("OAuth2 is not implemented in this build.")
        secret = self._secret()
        if not secret:
            raise RuntimeError("No password in keyring. Use Save Password first.")
        messages, debug = self.mcp_client.fetch_messages(settings, secret)
        self._debug(
            "MCP fetch debug: "
            f"candidate_count={debug.get('candidate_count', '?')}, "
            f"post_filter_count={debug.get('post_filter_count', '?')}, "
            f"mailbox={debug.get('mailbox', settings.mailbox)}"
        )
        return messages

    def _on_fetched(self, messages: list[EmailMessage]) -> None:
        self.messages = messages
        self.email_list.clear()
        self.attachments_list.clear()
        self.attachment_text.clear()
        for msg in messages:
            self.email_list.addItem(QListWidgetItem(f"{msg.date} | {msg.from_address} | {msg.subject}"))
        if not messages and self.target_to_input.text().strip():
            self.status.setText("Fetched 0 emails. Recipient filter may be too strict for provider headers.")
        else:
            self.status.setText(f"Fetched {len(messages)} emails")
        self._debug(f"Fetched {len(messages)} emails from Gmail/IMAP.")
        if messages:
            self.email_list.setCurrentRow(0)

    def _show_email_details(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.messages):
            return
        msg = self.messages[idx]
        self._debug(f"Selected email message_id={msg.message_id}, subject={msg.subject}")
        self.details.setPlainText(
            f"Date: {msg.date}\nFrom: {msg.from_address}\nTo: {msg.to_address}\nSubject: {msg.subject}\n\n"
            f"Snippet:\n{msg.snippet}\n\nBody:\n{msg.body}\n\nHeaders:\n{msg.raw_headers}"
        )
        self.attachments_list.clear()
        self.attachment_text.clear()
        if msg.attachments:
            for att in msg.attachments:
                status = "parsed" if att.extracted else "not parsed"
                self.attachments_list.addItem(f"{att.filename} ({att.content_type}) [{status}]")
            self.attachments_list.setCurrentRow(0)
        else:
            self.attachments_list.addItem("(no attachments)")
            self._debug("Selected email has no attachments.")

    def _show_attachment_details(self, idx: int) -> None:
        m_idx = self.email_list.currentRow()
        if m_idx < 0 or m_idx >= len(self.messages):
            self.attachment_text.clear()
            return
        msg = self.messages[m_idx]
        if not msg.attachments:
            self.attachment_text.setPlainText("No attachments on selected email.")
            return
        if idx < 0 or idx >= len(msg.attachments):
            self.attachment_text.clear()
            return
        att = msg.attachments[idx]
        extracted = att.extracted_text.strip() or "[No extracted text. Unsupported type or empty content.]"
        self.attachment_text.setPlainText(
            f"Filename: {att.filename}\n"
            f"Content-Type: {att.content_type}\n"
            f"Extracted: {att.extracted}\n\n"
            f"{extracted}"
        )

    def _process_selected(self) -> None:
        idx = self.email_list.currentRow()
        if idx < 0 or idx >= len(self.messages):
            self.status.setText("Select an email first.")
            return
        worker = Worker(self._process_one, self.messages[idx])
        worker.signals.started.connect(lambda: self.status.setText("Processing selected email..."))
        worker.signals.started.connect(lambda: self._debug("Processing selected email -> subject search + report."))
        worker.signals.finished.connect(self._process_finished)
        worker.signals.error.connect(lambda e: self.status.setText(f"Processing failed: {e}"))
        worker.signals.error.connect(lambda e: self._debug(f"Processing selected failed: {e}"))
        self.pool.start(worker)

    def _process_all(self) -> None:
        worker = Worker(self._process_all_task)
        worker.signals.started.connect(lambda: self.status.setText("Processing all fetched emails..."))
        worker.signals.started.connect(lambda: self._debug(f"Processing all fetched emails ({len(self.messages)} total)."))
        worker.signals.finished.connect(lambda n: self.status.setText(f"Processed {n} emails"))
        worker.signals.finished.connect(lambda n: self._debug(f"Processed {n} emails in batch."))
        worker.signals.error.connect(lambda e: self.status.setText(f"Batch processing failed: {e}"))
        worker.signals.error.connect(lambda e: self._debug(f"Batch processing failed: {e}"))
        self.pool.start(worker)

    def _process_all_task(self) -> int:
        count = 0
        for msg in self.messages:
            self._process_one(msg)
            count += 1
        return count

    def _process_one(self, msg: EmailMessage) -> dict:
        subject = msg.subject or ""
        query = subject if self.raw_subject_toggle.isChecked() else self.normalizer.normalize(subject)
        results = self.text_service.search(query, TextSearchScopes(), limit=10)
        report_path = self.report_writer.write_email_report(msg, query, results, index_version="fts5-v1")
        return {
            "query": query,
            "results": results,
            "report_path": str(report_path),
            "message_id": msg.message_id,
        }

    def _process_finished(self, payload: dict) -> None:
        self.search_results.clear()
        self.latest_results = payload["results"]
        for result in payload["results"]:
            self.search_results.addItem(
                f"{result.platform} | {result.title} | SKU {result.sku} | {result.path} | score {result.score:.4f}"
            )
        self.status.setText(f"Query: {payload['query']} | Report: {payload['report_path']}")
        self._debug(
            f"Processed message_id={payload.get('message_id','?')}, query={payload['query']!r}, "
            f"matches={len(payload['results'])}, report={payload['report_path']}"
        )
        self._debug(f"UI updated with {len(payload['results'])} search matches.")

    def _open_selected_in_finder(self) -> None:
        idx = self.search_results.currentRow()
        if idx < 0 or idx >= len(self.latest_results):
            self.status.setText("Select a result first.")
            return
        target = self.latest_results[idx].path
        subprocess.run(["open", target], check=False)

    def _cancel(self) -> None:
        self.cancel.cancel()
        self.status.setText("Cancel requested...")
        self._debug("Cancel requested by user.")
