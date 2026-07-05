"""The main application window.

Layout:
  ┌───────────────────────────────────────────────────────────────┐
  │ Title                                   [Groq chip] [Settings] │
  ├──────────────┬────────────────────────────────────────────────┤
  │ Run config   │  stat cards (visited / findings / tests / iter) │
  │ (URL, auth,  │  status line + current URL                      │
  │  options)    │  ┌────────────────────────────────────────────┐ │
  │  Run / Stop  │  │ tabs: Log · Findings · Tests · Coverage ·  │ │
  │  Capture     │  │       Report                               │ │
  │  Login       │  └────────────────────────────────────────────┘ │
  │              │                                                  │
  │ History      │                                                  │
  │ (past runs)  │                                                  │
  └──────────────┴────────────────────────────────────────────────┘
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.dialogs import LoginDialog, SettingsDialog
from gui.paths import (
    DEFAULT_AUTH,
    PROJECT_ROOT,
    groq_key_present,
    has_saved_session,
    load_env,
)
from gui.report_loader import list_runs, load_run
from gui.widgets import CoverageList, FindingsTable, StatCard, TestResultsTree
from gui.workers import RunConfig, RunWorker

_PRESET_URLS = [
    "https://demoqa.com/automation-practice-form",
    "https://demoqa.com/text-box",
    "http://localhost:5173",
]


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("QA Agent")
        self.resize(1280, 820)

        self._thread: QThread | None = None
        self._worker: RunWorker | None = None
        self._auth_path: Path = DEFAULT_AUTH

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(12)

        root.addLayout(self._build_header())

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_left_panel())
        split.addWidget(self._build_right_panel())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([340, 940])
        root.addWidget(split, 1)

        self.refresh_history()
        self.refresh_auth_status()

    # ------------------------------------------------------------------ #
    # Header
    # ------------------------------------------------------------------ #
    def _build_header(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("QA Agent")
        title.setObjectName("Title")
        sub = QLabel("Autonomous web QA — explore, generate tests, report bugs")
        sub.setObjectName("Subtitle")
        titles.addWidget(title)
        titles.addWidget(sub)
        bar.addLayout(titles)
        bar.addStretch(1)

        self.groq_chip = QLabel("Groq: ?")
        self.groq_chip.setObjectName("ChipWarn")
        bar.addWidget(self.groq_chip)

        settings_btn = QPushButton("⚙  Settings")
        settings_btn.clicked.connect(self._open_settings)
        bar.addWidget(settings_btn)
        self._refresh_groq_chip()
        return bar

    # ------------------------------------------------------------------ #
    # Left panel: configuration + history
    # ------------------------------------------------------------------ #
    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # --- config card ---
        card = QFrame()
        card.setObjectName("Card")
        form = QVBoxLayout(card)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)

        form.addWidget(_section("New run"))

        form.addWidget(QLabel("LLM provider"))
        self.provider_box = QComboBox()
        # (label shown to user, value passed to get_provider)
        self.provider_box.addItem("Groq (cloud — Llama 3.3 70B)", "groq")
        self.provider_box.addItem("Ollama (local — gemma4:e4b)", "ollama")
        self.provider_box.currentIndexChanged.connect(self._on_provider_changed)
        form.addWidget(self.provider_box)

        form.addWidget(QLabel("Target URL"))
        self.url_edit = QComboBox()
        self.url_edit.setEditable(True)
        self.url_edit.addItems(_PRESET_URLS)
        self.url_edit.setCurrentText(_PRESET_URLS[0])
        form.addWidget(self.url_edit)

        # This SPA navigates by buttons, so the crawler can't discover pages from
        # <a href> links. Let the user list extra pages to test directly; these seed
        # the crawl frontier so each one gets visited and tested.
        form.addWidget(QLabel("Also test these pages (optional — one URL per line)"))
        self.routes_edit = QPlainTextEdit()
        self.routes_edit.setPlaceholderText(
            "http://192.168.0.191:8000/accounting/cash-in/opd\n"
            "http://192.168.0.191:8000/accounting/cash-in/general"
        )
        self.routes_edit.setMaximumHeight(80)
        self.routes_edit.setToolTip(
            "Pages the crawler can't reach on its own (this app navigates by buttons, "
            "not links). Each URL here is visited and tested. Capped by 'Max pages'."
        )
        form.addWidget(self.routes_edit)

        row = QHBoxLayout()
        locale_box = QVBoxLayout()
        locale_box.addWidget(QLabel("Locale (optional)"))
        self.locale_edit = QLineEdit()
        self.locale_edit.setPlaceholderText("e.g. IN, US")
        self.locale_edit.setMaximumWidth(110)
        locale_box.addWidget(self.locale_edit)
        row.addLayout(locale_box)

        depth_box = QVBoxLayout()
        depth_box.addWidget(QLabel("Max pages"))
        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(1, 100)
        self.depth_spin.setValue(12)
        depth_box.addWidget(self.depth_spin)
        row.addLayout(depth_box)
        row.addStretch(1)
        form.addLayout(row)

        self.headless_check = QCheckBox("Run browser in background (headless)")
        form.addWidget(self.headless_check)

        self.allow_all_check = QCheckBox("Sandbox: allow all actions (disable safety gate)")
        self.allow_all_check.setToolTip(
            "For dev/test targets only. Lets the agent click financial submits like "
            "'Submit Transaction' that the safety gate would otherwise block."
        )
        # Off by default: safety stays ON unless you deliberately opt into sandbox mode.
        # Only tick this for a throwaway dev box where real submits are fine.
        self.allow_all_check.setChecked(False)
        form.addWidget(self.allow_all_check)

        # auth
        form.addWidget(_section("Authentication"))
        self.auth_status = QLabel("")
        self.auth_status.setWordWrap(True)
        form.addWidget(self.auth_status)
        auth_row = QHBoxLayout()
        self.capture_btn = QPushButton("Capture Login…")
        self.capture_btn.clicked.connect(self._capture_login)
        choose_btn = QPushButton("Use file…")
        choose_btn.clicked.connect(self._choose_auth)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_auth)
        auth_row.addWidget(self.capture_btn)
        auth_row.addWidget(choose_btn)
        auth_row.addWidget(clear_btn)
        form.addLayout(auth_row)

        # run controls
        controls = QHBoxLayout()
        self.run_btn = QPushButton("▶  Run")
        self.run_btn.setObjectName("Primary")
        self.run_btn.clicked.connect(self._start_run)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_run)
        controls.addWidget(self.run_btn, 2)
        controls.addWidget(self.stop_btn, 1)
        form.addLayout(controls)

        lay.addWidget(card)

        # --- history card ---
        hist_card = QFrame()
        hist_card.setObjectName("Card")
        hist_lay = QVBoxLayout(hist_card)
        hist_lay.setContentsMargins(14, 14, 14, 14)
        hist_header = QHBoxLayout()
        hist_header.addWidget(_section("History"))
        hist_header.addStretch(1)
        refresh = QPushButton("↻")
        refresh.setMaximumWidth(36)
        refresh.clicked.connect(self.refresh_history)
        hist_header.addWidget(refresh)
        hist_lay.addLayout(hist_header)

        self.history_list = QListWidget()
        self.history_list.itemClicked.connect(self._open_history_item)
        hist_lay.addWidget(self.history_list)
        lay.addWidget(hist_card, 1)

        return panel

    # ------------------------------------------------------------------ #
    # Right panel: stats + tabs
    # ------------------------------------------------------------------ #
    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # stat cards
        cards = QHBoxLayout()
        self.card_visited = StatCard("Pages visited")
        self.card_findings = StatCard("Findings")
        self.card_tests = StatCard("Tests passed")
        self.card_iter = StatCard("Crawl laps")
        for c in (self.card_visited, self.card_findings, self.card_tests, self.card_iter):
            cards.addWidget(c)
        cards.addStretch(1)
        lay.addLayout(cards)

        # status line
        status_row = QHBoxLayout()
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("ChipOk")
        self.current_url = QLabel("")
        self.current_url.setStyleSheet("color: #717cb4;")
        self.current_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_row.addWidget(self.status_label)
        status_row.addWidget(self.current_url, 1)
        lay.addLayout(status_row)

        # tabs
        self.tabs = QTabWidget()
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)

        self.findings_table = FindingsTable()
        self.results_tree = TestResultsTree()
        self.coverage_list = CoverageList()
        self.report_view = self._build_report_tab()

        self.tabs.addTab(self.log_view, "Live Log")
        self.tabs.addTab(self.findings_table, "Findings")
        self.tabs.addTab(self.results_tree, "Test Results")
        self.tabs.addTab(self.coverage_list, "Coverage")
        self.tabs.addTab(self.report_view, "Report")
        lay.addWidget(self.tabs, 1)

        return panel

    def _build_report_tab(self) -> QWidget:
        from PySide6.QtWidgets import QTextBrowser

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.report_path_label = QLabel("No report yet.")
        self.report_path_label.setStyleSheet("color: #717cb4;")
        self.report_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.open_folder_btn = QPushButton("Open folder")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._open_report_folder)
        bar.addWidget(self.report_path_label, 1)
        bar.addWidget(self.open_folder_btn)
        v.addLayout(bar)

        self.report_browser = QTextBrowser()
        self.report_browser.setOpenExternalLinks(True)
        v.addWidget(self.report_browser, 1)
        self._report_folder: Path | None = None
        return w

    # ------------------------------------------------------------------ #
    # Run lifecycle
    # ------------------------------------------------------------------ #
    def _start_run(self) -> None:
        url = self.url_edit.currentText().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Enter a target URL to crawl.")
            return
        provider = self.provider_box.currentData()
        # Only Groq needs an API key; Ollama runs locally with no key.
        if provider == "groq" and not groq_key_present():
            QMessageBox.warning(
                self,
                "No Groq API key",
                "The agent needs a GROQ_API_KEY. Open Settings to add one, "
                "or switch the LLM provider to Ollama (local).",
            )
            self._open_settings()
            return

        routes = [
            line.strip()
            for line in self.routes_edit.toPlainText().splitlines()
            if line.strip()
        ]
        cfg = RunConfig(
            url=url,
            routes=routes,
            locale=self.locale_edit.text().strip() or None,
            auth_path=self._auth_path if has_saved_session(self._auth_path) else None,
            headless=self.headless_check.isChecked(),
            max_iterations=self.depth_spin.value(),
            allow_all=self.allow_all_check.isChecked(),
            provider=provider,
        )

        # reset views
        self.log_view.clear()
        self.findings_table.set_findings([])
        self.results_tree.set_results([])
        self.coverage_list.set_urls([])
        self._set_running(True)
        self.tabs.setCurrentWidget(self.log_view)

        self._thread = QThread(self)
        self._worker = RunWorker(cfg)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._on_log)
        self._worker.status.connect(self._on_status)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _stop_run(self) -> None:
        if self._worker:
            self.stop_btn.setEnabled(False)
            self._worker.request_stop()

    def _set_running(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.capture_btn.setEnabled(not running)
        self.status_label.setText("Running" if running else "Idle")
        self.status_label.setObjectName("ChipWarn" if running else "ChipOk")
        self._restyle(self.status_label)

    def _on_log(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    def _on_status(self, text: str) -> None:
        if self.run_btn.isEnabled():  # not running -> don't override Idle styling
            return
        self.status_label.setText(text)

    def _on_progress(self, state: dict) -> None:
        self.card_visited.set_value(len(state["visited"]))
        n_find = len(state["findings"])
        self.card_findings.set_value(n_find, "#f78c6c" if n_find else None)
        results = state["test_results"]
        # Count honestly by status: only pass/review cases have a real oracle, and
        # only "pass" counts as passed. error/skipped/info are excluded from the ratio.
        passed = sum(1 for r in results if r.get("status") == "pass")
        scored = sum(1 for r in results if r.get("status") in ("pass", "review"))
        self.card_tests.set_value(f"{passed}/{scored}" if scored else "0")
        self.card_iter.set_value(state["iteration"])
        if state.get("current_url"):
            self.current_url.setText("→ " + state["current_url"])

        self.findings_table.set_findings(state["findings"])
        self.results_tree.set_results(results)
        self.coverage_list.set_urls(state["visited"])

    def _on_finished(self, summary: dict) -> None:
        self._set_running(False)
        if summary.get("stopped"):
            label = "Stopped"
        elif summary.get("crashed"):
            label = "Finished with errors"
        else:
            label = "Done"
        self.status_label.setText(label)
        # final refresh from the authoritative summary
        self.findings_table.set_findings(summary["findings"])
        self.results_tree.set_results(summary["test_results"])
        self.coverage_list.set_urls(summary["visited"])
        self.card_visited.set_value(len(summary["visited"]))
        self.card_findings.set_value(len(summary["findings"]))
        self.card_tests.set_value(f"{summary['tests_passed']}/{summary['tests_total']}")
        self.card_iter.set_value(summary["iterations"])

        folder = Path(summary["report_dir"])
        self._show_report(folder)
        self.refresh_history()
        self.tabs.setCurrentWidget(self.report_view)

    def _on_failed(self, tb: str) -> None:
        self._set_running(False)
        self.status_label.setText("Error")
        self.status_label.setObjectName("ChipBad")
        self._restyle(self.status_label)
        self.log_view.appendPlainText("\n=== RUN FAILED ===\n" + tb)
        self.tabs.setCurrentWidget(self.log_view)
        QMessageBox.critical(self, "Run failed", tb.strip().splitlines()[-1] if tb.strip() else "Unknown error")

    # ------------------------------------------------------------------ #
    # Report tab
    # ------------------------------------------------------------------ #
    def _show_report(self, folder: Path) -> None:
        md_path = folder / "report.md"
        self._report_folder = folder
        self.report_path_label.setText(str(md_path))
        self.open_folder_btn.setEnabled(True)
        if md_path.exists():
            self.report_browser.setMarkdown(md_path.read_text(encoding="utf-8"))

    def _open_report_folder(self) -> None:
        if self._report_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._report_folder)))

    # ------------------------------------------------------------------ #
    # History
    # ------------------------------------------------------------------ #
    def refresh_history(self) -> None:
        self.history_list.clear()
        for run in list_runs():
            item = QListWidgetItem(run.label)
            item.setData(Qt.UserRole, str(run.path))
            self.history_list.addItem(item)

    def _open_history_item(self, item: QListWidgetItem) -> None:
        folder = Path(item.data(Qt.UserRole))
        run = load_run(folder)
        if run is None:
            return
        self.findings_table.set_findings(run.findings)
        self.results_tree.set_results(run.test_results)
        self.coverage_list.set_urls(run.visited_urls)
        self.card_visited.set_value(len(run.visited_urls))
        self.card_findings.set_value(len(run.findings))
        self.card_tests.set_value(f"{run.tests_passed}/{run.tests_scored}")
        self.card_iter.set_value("—")
        self.current_url.setText(f"(viewing past run: {run.name})")
        self._show_report(folder)
        self.tabs.setCurrentWidget(self.report_view)

    # ------------------------------------------------------------------ #
    # Auth + settings
    # ------------------------------------------------------------------ #
    def refresh_auth_status(self) -> None:
        if has_saved_session(self._auth_path):
            self.auth_status.setText(f"✓ Using session: {self._auth_path.name}")
            self.auth_status.setStyleSheet("color: #c3e88d;")
        else:
            self.auth_status.setText("No saved session — crawl runs unauthenticated.")
            self.auth_status.setStyleSheet("color: #717cb4;")

    def _capture_login(self) -> None:
        url = self.url_edit.currentText().strip()
        dlg = LoginDialog(self, default_url=url, auth_path=self._auth_path)
        dlg.exec()
        if dlg.saved_path and has_saved_session(dlg.saved_path):
            self._auth_path = dlg.saved_path
        self.refresh_auth_status()

    def _choose_auth(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select auth session", str(PROJECT_ROOT), "JSON (*.json)"
        )
        if path:
            self._auth_path = Path(path)
            self.refresh_auth_status()

    def _clear_auth(self) -> None:
        self._auth_path = DEFAULT_AUTH
        # don't delete the file; just stop using it unless it's a real session
        if not has_saved_session(self._auth_path):
            self.refresh_auth_status()
        else:
            self.auth_status.setText("Session present but cleared for this run (won't be used).")
            self.auth_status.setStyleSheet("color: #717cb4;")
            self._auth_path = Path("/nonexistent-session.json")

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self)
        if dlg.exec():
            self._refresh_groq_chip()

    def _on_provider_changed(self) -> None:
        # The header chip tracks whatever provider is selected.
        if self.provider_box.currentData() == "ollama":
            self.groq_chip.setText("Ollama: local (gemma4:e4b)")
            self.groq_chip.setObjectName("ChipOk")
            self._restyle(self.groq_chip)
        else:
            self._refresh_groq_chip()

    def _refresh_groq_chip(self) -> None:
        # When Ollama is selected the chip is owned by _on_provider_changed.
        if getattr(self, "provider_box", None) is not None and (
            self.provider_box.currentData() == "ollama"
        ):
            return
        load_env()
        if groq_key_present():
            self.groq_chip.setText("Groq: connected")
            self.groq_chip.setObjectName("ChipOk")
        else:
            self.groq_chip.setText("Groq: no key")
            self.groq_chip.setObjectName("ChipBad")
        self._restyle(self.groq_chip)

    # ------------------------------------------------------------------ #
    def _restyle(self, w: QWidget) -> None:
        """Re-apply the stylesheet after changing a widget's objectName."""
        w.style().unpolish(w)
        w.style().polish(w)

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._thread is not None and self._thread.isRunning():
            self._worker.request_stop()
            self._thread.quit()
            self._thread.wait(3000)
        super().closeEvent(event)


def _section(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("SectionHeader")
    return lbl
