"""A single dark stylesheet for the app, plus the severity/status colour map.

Kept in one place so the look is easy to tweak. Colours are loosely a
"Material Palenight" palette — calm, good contrast for long log sessions.
"""
from __future__ import annotations

# Severity → accent colour (matches the report's severity vocabulary).
SEVERITY_COLORS = {
    "critical": "#ff5370",
    "high": "#f78c6c",
    "medium": "#ffcb6b",
    "low": "#89ddff",
    "info": "#a6accd",
}

# Observed test outcome → colour.
OUTCOME_COLORS = {
    "accepted": "#c3e88d",
    "rejected": "#ffcb6b",
    "error": "#ff5370",
}

PASS_COLOR = "#c3e88d"
FAIL_COLOR = "#f78c6c"

# Test-case category → colour.
CATEGORY_COLORS = {
    "happy": "#c3e88d",
    "edge": "#ffcb6b",
    "scenario": "#82aaff",
}

BG = "#292d3e"
BG_RAISED = "#323750"
BG_SUNKEN = "#222637"
BORDER = "#3a3f58"
TEXT = "#c3cee3"
TEXT_DIM = "#717cb4"
ACCENT = "#82aaff"
ACCENT_HOVER = "#9bbbff"

STYLESHEET = f"""
* {{
    /* Families Qt resolves on macOS/Windows without the "missing font" warning. */
    font-family: "Helvetica Neue", "Segoe UI", Arial, sans-serif;
    font-size: 13px;
    color: {TEXT};
}}
QWidget {{ background: {BG}; }}

QMainWindow, QDialog {{ background: {BG}; }}

QLabel#Title {{ font-size: 18px; font-weight: 700; color: #ffffff; }}
QLabel#Subtitle {{ color: {TEXT_DIM}; }}
QLabel#SectionHeader {{ font-size: 13px; font-weight: 700; color: {ACCENT}; }}

/* Inputs */
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextBrowser {{
    background: {BG_SUNKEN};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {ACCENT};
    selection-color: #1b1e2b;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: 0; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: #1b1e2b;
}}

/* Buttons */
QPushButton {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 600;
}}
QPushButton:hover {{ border: 1px solid {ACCENT}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; background: {BG_SUNKEN}; }}

QPushButton#Primary {{ background: {ACCENT}; color: #1b1e2b; border: 0; }}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Primary:disabled {{ background: {BORDER}; color: {TEXT_DIM}; }}
QPushButton#Danger {{ background: #5a2a37; border: 1px solid #ff5370; color: #ffd7df; }}
QPushButton#Danger:hover {{ background: #6e3242; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {BORDER}; background: {BG_SUNKEN};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}

/* Cards / frames */
QFrame#Card {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#StatCard {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel#StatValue {{ font-size: 22px; font-weight: 700; color: #ffffff; }}
QLabel#StatLabel {{ color: {TEXT_DIM}; font-size: 11px; }}

/* Tabs */
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{
    background: transparent; padding: 8px 16px; margin-right: 2px;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
    color: {TEXT_DIM};
}}
QTabBar::tab:selected {{ background: {BG_RAISED}; color: #ffffff; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

/* Tables / trees / lists */
QTableWidget, QTreeWidget, QListWidget {{
    background: {BG_SUNKEN};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: {BORDER};
    alternate-background-color: #262a3b;
    outline: 0;
}}
QHeaderView::section {{
    background: {BG_RAISED};
    color: {TEXT_DIM};
    padding: 6px 8px;
    border: 0;
    border-bottom: 1px solid {BORDER};
    font-weight: 600;
}}
QTableWidget::item, QTreeWidget::item {{ padding: 4px 6px; }}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {ACCENT}; color: #1b1e2b;
}}
QListWidget::item {{ padding: 8px; border-radius: 6px; }}
QListWidget::item:hover {{ background: {BG_RAISED}; }}

/* Log console */
QPlainTextEdit#Log {{
    font-family: "SF Mono", "JetBrains Mono", Menlo, monospace;
    font-size: 12px;
    background: #1b1e2b;
    color: #d3d7ee;
}}

/* Status chips */
QLabel#ChipOk {{ background: #2c4a3a; color: {PASS_COLOR}; border-radius: 10px; padding: 3px 10px; font-weight: 600; }}
QLabel#ChipWarn {{ background: #4a3a2c; color: #ffcb6b; border-radius: 10px; padding: 3px 10px; font-weight: 600; }}
QLabel#ChipBad {{ background: #4a2c34; color: #ff5370; border-radius: 10px; padding: 3px 10px; font-weight: 600; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 30px; }}

QSplitter::handle {{ background: {BORDER}; }}
QToolTip {{ background: {BG_RAISED}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
"""
