"""Entry point for the QA Agent desktop GUI.

Run it with:
    uv run qa-agent-gui
    # or
    uv run python -m gui.app
"""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        sys.stderr.write(
            "PySide6 is not installed. Install the GUI extras with:\n"
            "    uv sync --group gui\n"
            "or:\n"
            "    uv pip install pyside6\n"
        )
        return 1

    from PySide6.QtCore import QTimer

    from gui.main_window import MainWindow
    from gui.paths import load_env
    from gui.theme import STYLESHEET

    load_env()  # pick up GROQ_API_KEY from .env / .env.local before the UI opens

    app = QApplication(sys.argv)
    app.setApplicationName("QA Agent")
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.show()

    # On macOS a window launched from a plain console script (no .app bundle) tends
    # to open *behind* the terminal with no focus. Force it to the foreground — once
    # now, and again just after the event loop starts (the second one actually wins).
    def _to_front() -> None:
        window.raise_()
        window.activateWindow()

    _to_front()
    QTimer.singleShot(150, _to_front)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
