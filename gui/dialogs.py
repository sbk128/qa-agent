"""Modal dialogs: app settings and the manual-login capture flow."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from gui.paths import DEFAULT_AUTH, set_env_value
from gui.workers import LoginWorker


# --------------------------------------------------------------------------- #
# Settings — manage the Groq API key + provider (written to .env.local)
# --------------------------------------------------------------------------- #
class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)

        lay = QVBoxLayout(self)

        intro = QLabel(
            "The agent uses Groq for LLM calls. Your key is saved to "
            "<code>.env.local</code> (gitignored) and never committed."
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(10)

        self.key_edit = QLineEdit(os.environ.get("GROQ_API_KEY", ""))
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("gsk_…")
        show = QPushButton("Show")
        show.setCheckable(True)
        show.toggled.connect(
            lambda on: self.key_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        )
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit)
        key_row.addWidget(show)
        form.addRow("GROQ_API_KEY", _wrap(key_row))

        self.provider = QComboBox()
        self.provider.addItem("groq")
        self.provider.setCurrentText(os.environ.get("LLM_PROVIDER", "groq"))
        form.addRow("LLM_PROVIDER", self.provider)

        lay.addLayout(form)

        hint = QLabel('Get a key at <a href="https://console.groq.com/keys">console.groq.com/keys</a>')
        hint.setOpenExternalLinks(True)
        hint.setStyleSheet("color: #717cb4;")
        lay.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _save(self) -> None:
        key = self.key_edit.text().strip()
        if key:
            set_env_value("GROQ_API_KEY", key)
        set_env_value("LLM_PROVIDER", self.provider.currentText().strip() or "groq")
        self.accept()


# --------------------------------------------------------------------------- #
# Login capture — open a headed browser, wait for a manual login, save auth.json
# --------------------------------------------------------------------------- #
class LoginDialog(QDialog):
    def __init__(self, parent=None, default_url: str = "", auth_path: Path | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Capture Login Session")
        self.setMinimumWidth(560)
        self._auth_path = auth_path or DEFAULT_AUTH
        self._thread: QThread | None = None
        self._worker: LoginWorker | None = None
        self.saved_path: Path | None = None

        lay = QVBoxLayout(self)

        info = QLabel(
            "Opens a browser at your login page. Log in by hand, then click "
            "<b>I've logged in</b>. The session (cookies + token) is saved so the "
            "agent can crawl pages behind auth. The agent never types your credentials."
        )
        info.setWordWrap(True)
        lay.addWidget(info)

        form = QFormLayout()
        self.url_edit = QLineEdit(default_url)
        self.url_edit.setPlaceholderText("http://host/login")
        form.addRow("Login URL", self.url_edit)
        form.addRow("Save to", QLabel(str(self._auth_path)))
        lay.addLayout(form)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #82aaff;")
        lay.addWidget(self.status)

        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        lay.addWidget(self.log)

        row = QHBoxLayout()
        self.open_btn = QPushButton("Open browser")
        self.open_btn.setObjectName("Primary")
        self.open_btn.clicked.connect(self._open)
        self.done_btn = QPushButton("I've logged in")
        self.done_btn.setEnabled(False)
        self.done_btn.clicked.connect(self._mark_done)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)
        row.addWidget(self.open_btn)
        row.addWidget(self.done_btn)
        row.addStretch(1)
        row.addWidget(self.close_btn)
        lay.addLayout(row)

    def _open(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            self.status.setText("Enter a login URL first.")
            return
        self.open_btn.setEnabled(False)
        self.url_edit.setEnabled(False)

        self._thread = QThread(self)
        self._worker = LoginWorker(url, self._auth_path)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(lambda m: self.log.appendPlainText(m))
        self._worker.status.connect(self._on_status)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_status(self, text: str) -> None:
        self.status.setText(text)
        if "log in" in text.lower():
            self.done_btn.setEnabled(True)

    def _mark_done(self) -> None:
        if self._worker:
            self.done_btn.setEnabled(False)
            self.status.setText("Saving session…")
            self._worker.mark_done()

    def _on_finished(self, info: dict) -> None:
        self.saved_path = Path(info["path"])
        if info["looks_empty"]:
            self.status.setText("⚠️ Session looks empty — were you actually logged in? Try again.")
            self.open_btn.setEnabled(True)
            self.url_edit.setEnabled(True)
        else:
            self.status.setText(
                f"✓ Saved {info['cookies']} cookie(s), {info['origins']} origin(s) to {info['path']}"
            )
            self.close_btn.setText("Done")

    def _on_failed(self, tb: str) -> None:
        self.status.setText("Login capture failed — see log.")
        self.log.appendPlainText(tb)
        self.open_btn.setEnabled(True)
        self.url_edit.setEnabled(True)


def _wrap(layout) -> "QWidget":
    from PySide6.QtWidgets import QWidget

    w = QWidget()
    layout.setContentsMargins(0, 0, 0, 0)
    w.setLayout(layout)
    return w
