"""Reusable result widgets.

Each panel consumes the *dict* form of the agent's models (i.e. `model_dump()`,
the same shape stored in `report.json`). That way the live run view and the
history view render through identical code — no special-casing.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.theme import (
    CATEGORY_COLORS,
    FAIL_COLOR,
    OUTCOME_COLORS,
    PASS_COLOR,
    SEVERITY_COLORS,
    TEXT_DIM,
)


# --------------------------------------------------------------------------- #
# Stat card — one big number with a label
# --------------------------------------------------------------------------- #
class StatCard(QFrame):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.setObjectName("StatCard")
        self.setMinimumWidth(120)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)

        self._value = QLabel("—")
        self._value.setObjectName("StatValue")
        self._label = QLabel(label)
        self._label.setObjectName("StatLabel")
        lay.addWidget(self._value)
        lay.addWidget(self._label)

    def set_value(self, value, color: str | None = None) -> None:
        self._value.setText(str(value))
        if color:
            self._value.setStyleSheet(f"color: {color};")


# --------------------------------------------------------------------------- #
# Findings table
# --------------------------------------------------------------------------- #
class FindingsTable(QWidget):
    """Severity-sorted, deduplicated findings — mirrors the report's grouping."""

    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Severity", "Category", "Title", "Description", "URL"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 200)
        self.table.setColumnWidth(4, 220)

        self._empty = QLabel("No findings yet.")
        self._empty.setStyleSheet(f"color: {TEXT_DIM};")
        self._empty.setAlignment(Qt.AlignCenter)

        lay.addWidget(self._empty)
        lay.addWidget(self.table)
        self.table.hide()

    _SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

    def set_findings(self, findings: list[dict]) -> None:
        # Deduplicate exactly like report.build_report: (severity, category, desc, url).
        groups: dict = {}
        for f in findings:
            key = (f.get("severity"), f.get("category"), f.get("description"), f.get("url"))
            if key not in groups:
                groups[key] = {"f": f, "count": 0}
            groups[key]["count"] += 1
        unique = sorted(groups.values(), key=lambda g: self._SEV_ORDER.get(g["f"].get("severity"), 99))

        self.table.setRowCount(0)
        if not unique:
            self.table.hide()
            self._empty.show()
            return
        self._empty.hide()
        self.table.show()

        for g in unique:
            f = g["f"]
            row = self.table.rowCount()
            self.table.insertRow(row)
            sev = (f.get("severity") or "info").lower()

            sev_item = QTableWidgetItem(sev.upper())
            sev_item.setForeground(QColor(SEVERITY_COLORS.get(sev, "#a6accd")))
            sev_item.setFont(_bold())

            title = f.get("title", "")
            if g["count"] > 1:
                title += f"  (×{g['count']})"

            self.table.setItem(row, 0, sev_item)
            self.table.setItem(row, 1, QTableWidgetItem(f.get("category", "")))
            self.table.setItem(row, 2, QTableWidgetItem(title))
            self.table.setItem(row, 3, QTableWidgetItem(f.get("description", "")))
            self.table.setItem(row, 4, QTableWidgetItem(f.get("url", "")))
        self.table.resizeRowsToContents()


# --------------------------------------------------------------------------- #
# Test-results tree — grouped by URL, one child per case
# --------------------------------------------------------------------------- #
class TestResultsTree(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.summary = QLabel("No tests run yet.")
        self.summary.setStyleSheet(f"color: {TEXT_DIM}; padding: 2px 2px 6px 2px;")

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Case", "Category", "Expected", "Observed", "Detail"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.Stretch)
        self.tree.setColumnWidth(0, 280)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 90)
        self.tree.setColumnWidth(3, 90)

        lay.addWidget(self.summary)
        lay.addWidget(self.tree)

    _MARKS = {"pass": "✓", "review": "⚑ review", "info": "• info",
              "error": "✗ error", "skipped": "– skipped"}

    @staticmethod
    def _status(r: dict) -> str:
        # Prefer the computed status; fall back for older report.json without it.
        return r.get("status") or ("pass" if r.get("passed") else "review")

    def set_results(self, results: list[dict]) -> None:
        self.tree.clear()
        if not results:
            self.summary.setText("No tests run yet.")
            return

        passed = sum(1 for r in results if self._status(r) == "pass")
        scored = sum(1 for r in results if self._status(r) in ("pass", "review"))
        n_pages = len(set(r.get("url") for r in results))
        self.summary.setText(
            f"<b>{passed}/{scored}</b> cases passed across {n_pages} page(s) "
            f"(cases without a clear right answer aren't scored)"
        )

        by_url: dict[str, list[dict]] = {}
        for r in results:
            by_url.setdefault(r.get("url", ""), []).append(r)

        for url, page_results in by_url.items():
            page_passed = sum(1 for r in page_results if self._status(r) == "pass")
            page_scored = sum(1 for r in page_results if self._status(r) in ("pass", "review"))
            parent = QTreeWidgetItem([f"{url}   —   {page_passed}/{page_scored} passed"])
            parent.setFirstColumnSpanned(True)
            parent.setFont(0, _bold())
            self.tree.addTopLevelItem(parent)

            for r in page_results:
                case = r.get("case", {})
                status = self._status(r)
                mark = self._MARKS.get(status, status)
                observed = r.get("observed", "")
                child = QTreeWidgetItem(
                    [
                        f"{mark}  {case.get('name', '')}",
                        case.get("category", ""),
                        case.get("expected", ""),
                        observed,
                        r.get("detail", ""),
                    ]
                )
                colour = PASS_COLOR if status == "pass" else (
                    FAIL_COLOR if status in ("review", "error") else TEXT_DIM
                )
                child.setForeground(0, QColor(colour))
                child.setForeground(1, QColor(CATEGORY_COLORS.get(case.get("category"), "#c3cee3")))
                child.setForeground(3, QColor(OUTCOME_COLORS.get(observed, "#c3cee3")))
                tip = (
                    f"{case.get('description','')}\n\nRationale: {case.get('rationale','')}\n\n"
                    f"Values: {case.get('field_values', {})}"
                )
                child.setToolTip(0, tip)
                parent.addChild(child)
            parent.setExpanded(True)


# --------------------------------------------------------------------------- #
# Coverage list — visited URLs
# --------------------------------------------------------------------------- #
class CoverageList(QWidget):
    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.header = QLabel("Pages visited")
        self.header.setObjectName("SectionHeader")
        self.list = QListWidget()
        lay.addWidget(self.header)
        lay.addWidget(self.list)

    def set_urls(self, urls: list[str]) -> None:
        self.list.clear()
        self.header.setText(f"Pages visited — {len(urls)}")
        for u in urls:
            self.list.addItem(QListWidgetItem(u))


def _bold() -> QFont:
    f = QFont()
    f.setBold(True)
    return f
