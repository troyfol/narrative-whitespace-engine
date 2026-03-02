#!/usr/bin/env python
"""Narrative Whitespace Engine — Desktop GUI launcher."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from gui.style import APP_STYLE


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Narrative Whitespace Engine")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
