from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from dotenv import load_dotenv

from sold_item_finder.ui.main_window import MainWindow


def main() -> int:
    # Load local .env so OPENAI_API_KEY can be configured per project.
    load_dotenv()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
