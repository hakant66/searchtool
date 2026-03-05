from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout


class _CropLabel(QLabel):
    def __init__(self, pixmap: QPixmap) -> None:
        super().__init__()
        self._original = pixmap
        self._display = pixmap.scaled(
            QSize(1000, 700),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(self._display)
        self.setFixedSize(self._display.size())
        self._drag_start: QPoint | None = None
        self._selection = QRect()

    @property
    def selection(self) -> QRect:
        return self._selection.normalized()

    @property
    def original_pixmap(self) -> QPixmap:
        return self._original

    @property
    def display_pixmap(self) -> QPixmap:
        return self._display

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._selection = QRect(self._drag_start, self._drag_start)
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._drag_start is not None:
            current = event.position().toPoint()
            self._selection = QRect(self._drag_start, current)
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            current = event.position().toPoint()
            self._selection = QRect(self._drag_start, current).normalized()
            self._drag_start = None
            self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if self._selection.isNull():
            return
        painter = QPainter(self)
        painter.setPen(QPen(Qt.GlobalColor.red, 2, Qt.PenStyle.SolidLine))
        painter.drawRect(self._selection.normalized())
        painter.end()


class ImageCropDialog(QDialog):
    def __init__(self, image_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Crop Query Image")
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            raise ValueError(f"Failed to load image: {image_path}")
        self.crop_label = _CropLabel(pixmap)

        layout = QVBoxLayout(self)
        layout.addWidget(self.crop_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_cropped(self) -> QPixmap:
        selection = self.crop_label.selection
        if selection.width() < 2 or selection.height() < 2:
            return self.crop_label.original_pixmap

        display = self.crop_label.display_pixmap
        original = self.crop_label.original_pixmap
        scale_x = original.width() / max(display.width(), 1)
        scale_y = original.height() / max(display.height(), 1)
        orig_rect = QRect(
            int(selection.x() * scale_x),
            int(selection.y() * scale_y),
            int(selection.width() * scale_x),
            int(selection.height() * scale_y),
        ).intersected(original.rect())
        if orig_rect.width() < 2 or orig_rect.height() < 2:
            return original
        return original.copy(orig_rect)


class CroppedPreviewDialog(QDialog):
    def __init__(self, cropped_pixmap: QPixmap, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preview Cropped Image")
        layout = QVBoxLayout(self)

        preview = QLabel()
        scaled = cropped_pixmap.scaled(
            QSize(800, 500),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        preview.setPixmap(scaled)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
