"""
KHUx File Explorer - FModel-style 3-pane GUI for browsing KHUx game containers.
Launch: python -m gui.app

PyQt6 implementation.
"""

import json
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QPlainTextEdit, QLabel, QPushButton, QLineEdit, QHBoxLayout,
    QVBoxLayout, QStatusBar, QMenuBar, QMenu, QFileDialog, QMessageBox,
    QScrollArea, QSizePolicy, QFrame,
)
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QPixmap, QImage, QPalette, QColor, QFont, QAction, QShortcut,
    QKeySequence, QIcon, QWheelEvent, QPainter, QBrush, QClipboard,
    QTextCharFormat, QTextCursor,
)

# Ensure project root is on path
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from khux.containers import KHUxBGADContainer, BGADEntry
from khux.detect import detect_format
from khux.models.bgad import BGADHeader

# Optional imports - graceful degradation
try:
    from khux.formats import KHUxBTF
    HAS_BTF = True
except ImportError:
    HAS_BTF = False

try:
    from khux.formats import KHUxAvatar
    HAS_AVATAR = True
except ImportError:
    HAS_AVATAR = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import io as _io
    from khux.containers.bgi import KHUxBGI
    from khux.utils.crypto import KEY_APK, KEY_DOWNLOAD
    HAS_BGI = True
except ImportError:
    HAS_BGI = False

try:
    from khux.formats.avatar import decrypt_master_data_payload, AvatarPartDecrypted
    HAS_MASTER_DATA = True
except ImportError:
    HAS_MASTER_DATA = False


# ---------------------------------------------------------------------------
# Dark theme colors
# ---------------------------------------------------------------------------
COLORS = {
    "bg":           "#1e1e1e",
    "bg_alt":       "#252526",
    "bg_lighter":   "#2d2d30",
    "fg":           "#cccccc",
    "fg_dim":       "#808080",
    "fg_bright":    "#e0e0e0",
    "accent":       "#007acc",
    "accent_hover": "#1c97ea",
    "border":       "#3c3c3c",
    "selection":    "#264f78",
    "tree_bg":      "#1e1e1e",
    "text_bg":      "#1e1e1e",
    "status_bg":    "#007acc",
    "status_fg":    "#ffffff",
    "error":        "#f44747",
    "warning":      "#cca700",
    "success":      "#4ec9b0",
}

FORMAT_COLORS = {
    "btf":     "#4ec9b0",
    "lwf":     "#c586c0",
    "akb":     "#ce9178",
    "plist":   "#dcdcaa",
    "json":    "#dcdcaa",
    "stg":     "#569cd6",
    "map":     "#569cd6",
    "bgi":     "#d7ba7d",
    "bgad":    "#d7ba7d",
    "unknown": "#808080",
}

FORMAT_BADGES = {
    "btf":     "[BTF]",
    "lwf":     "[LWF]",
    "akb":     "[AKB]",
    "plist":   "[PLIST]",
    "stg":     "[STG]",
    "map":     "[MAP]",
    "bgi":     "[BGI]",
    "bgad":    "[BGAD]",
    "jmp":     "[JMP]",
    "bmi":     "[BMI]",
    "cls":     "[CLS]",
    "chp":     "[CHP]",
    "index":   "[IDX]",
    "unknown": "[???]",
}

# Tree item data roles
ROLE_ENTRY_NAME = Qt.ItemDataRole.UserRole
ROLE_FORMAT = Qt.ItemDataRole.UserRole + 1


def _hex_dump(data: bytes, length: int = 256, cols: int = 16) -> str:
    """Format bytes as a hex dump string."""
    data = data[:length]
    lines = []
    for i in range(0, len(data), cols):
        chunk = data[i:i + cols]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:08x}  {hex_part:<{cols * 3}}  {ascii_part}")
    return "\n".join(lines)


def _format_size(size: int) -> str:
    """Human readable file size."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.2f} MB"


def _pil_image_to_qpixmap(pil_img: "Image.Image") -> QPixmap:
    """Convert a PIL Image to QPixmap."""
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.width, pil_img.height, 4 * pil_img.width,
                  QImage.Format.Format_RGBA8888)
    # QImage references external data buffer, so we must copy
    return QPixmap.fromImage(qimg.copy())


# ---------------------------------------------------------------------------
# Zoomable image preview widget
# ---------------------------------------------------------------------------
class ImagePreviewWidget(QScrollArea):
    """Scrollable, zoomable image preview with checkerboard transparency background."""

    zoom_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background-color: {COLORS['bg_alt']}; border: none;")

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setWidget(self._label)

        self._pixmap: Optional[QPixmap] = None
        self._zoom: float = 1.0
        self._original_size: QSize = QSize(0, 0)
        self._size_text: str = ""

    def set_pixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self._original_size = pixmap.size()
        self._size_text = f"{pixmap.width()} x {pixmap.height()}"
        self._zoom = 1.0
        self._update_display()

    def clear_image(self):
        self._pixmap = None
        self._label.clear()
        self._label.resize(0, 0)
        self._size_text = ""

    def zoom_in(self):
        self._zoom = min(self._zoom * 1.5, 10.0)
        self._update_display()
        return self._zoom

    def zoom_out(self):
        self._zoom = max(self._zoom / 1.5, 0.1)
        self._update_display()
        return self._zoom

    def zoom_level(self) -> float:
        return self._zoom

    def size_text(self) -> str:
        return self._size_text

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and self._pixmap:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
            self.zoom_changed.emit(self._zoom)
            event.accept()
        else:
            super().wheelEvent(event)

    def _update_display(self):
        if self._pixmap is None:
            return

        vp = self.viewport().size()
        ow, oh = self._original_size.width(), self._original_size.height()
        if ow == 0 or oh == 0:
            return

        if self._zoom == 1.0:
            # Fit to viewport without upscaling
            scale_w = vp.width() / ow
            scale_h = vp.height() / oh
            scale = min(scale_w, scale_h, 1.0)
        else:
            scale_w = vp.width() / ow
            scale_h = vp.height() / oh
            base_scale = min(scale_w, scale_h, 1.0)
            scale = base_scale * self._zoom

        new_w = max(1, int(ow * scale))
        new_h = max(1, int(oh * scale))

        scaled = self._pixmap.scaled(
            new_w, new_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # Draw checkerboard + image
        result = QPixmap(scaled.size())
        painter = QPainter(result)
        cell = 16
        c1 = QColor("#2a2a2a")
        c2 = QColor("#323232")
        for y in range(0, scaled.height(), cell):
            for x in range(0, scaled.width(), cell):
                color = c1 if (x // cell + y // cell) % 2 == 0 else c2
                painter.fillRect(x, y, cell, cell, QBrush(color))
        painter.drawPixmap(0, 0, scaled)
        painter.end()

        self._label.setPixmap(result)
        self._label.resize(result.size())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap:
            self._update_display()

    def show_error(self, text: str):
        self._pixmap = None
        self._label.setText(text)
        self._label.setStyleSheet(f"color: {COLORS['error']}; font: 10pt 'Consolas';")
        self._label.adjustSize()


# ---------------------------------------------------------------------------
# Styled read-only text widget
# ---------------------------------------------------------------------------
class StyledTextEdit(QPlainTextEdit):
    """Read-only monospace text area with dark theme."""

    def __init__(self, parent=None, wrap: bool = True):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", 10))
        wrap_mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth if wrap
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        self.setLineWrapMode(wrap_mode)
        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {COLORS['text_bg']};
                color: {COLORS['fg']};
                border: none;
                padding: 8px;
                selection-background-color: {COLORS['selection']};
            }}
        """)


# ---------------------------------------------------------------------------
# Rich-text properties widget using QTextEdit for colored text
# ---------------------------------------------------------------------------
from PyQt6.QtWidgets import QTextEdit


class PropertiesTextEdit(QTextEdit):
    """Read-only rich text area for the properties panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", 10))
        self.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['text_bg']};
                color: {COLORS['fg']};
                border: none;
                padding: 8px;
                selection-background-color: {COLORS['selection']};
            }}
        """)

    def append_header(self, text: str):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(COLORS["accent"]))
        fmt.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text + "\n", fmt)

    def append_separator(self):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(COLORS["fg_dim"]))
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText("-" * 40 + "\n\n", fmt)

    def append_kv(self, key: str, value: str):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        key_fmt = QTextCharFormat()
        key_fmt.setForeground(QColor("#569cd6"))
        key_fmt.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        cursor.insertText(f"  {key}: ", key_fmt)

        val_fmt = QTextCharFormat()
        val_fmt.setForeground(QColor(COLORS["fg"]))
        val_fmt.setFont(QFont("Consolas", 10))
        cursor.insertText(f"{value}\n", val_fmt)

    def append_dim(self, text: str):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(COLORS["fg_dim"]))
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text + "\n", fmt)


# ---------------------------------------------------------------------------
# Global stylesheet
# ---------------------------------------------------------------------------
DARK_STYLESHEET = f"""
QMainWindow {{
    background-color: {COLORS['bg']};
}}
QWidget {{
    background-color: {COLORS['bg']};
    color: {COLORS['fg']};
    font-family: 'Segoe UI', sans-serif;
    font-size: 10pt;
}}
QSplitter::handle {{
    background-color: {COLORS['border']};
    width: 4px;
}}
QTreeWidget {{
    background-color: {COLORS['tree_bg']};
    color: {COLORS['fg']};
    border: none;
    outline: none;
    font-family: 'Segoe UI', sans-serif;
    font-size: 10pt;
}}
QTreeWidget::item {{
    padding: 2px 0px;
    min-height: 22px;
}}
QTreeWidget::item:selected {{
    background-color: {COLORS['selection']};
    color: {COLORS['fg_bright']};
}}
QTreeWidget::item:hover {{
    background-color: {COLORS['bg_lighter']};
}}
QTreeWidget::branch {{
    background-color: {COLORS['tree_bg']};
}}
QHeaderView::section {{
    background-color: {COLORS['bg_lighter']};
    color: {COLORS['fg']};
    border: none;
    padding: 4px;
}}
QTabWidget::pane {{
    border: none;
    background-color: {COLORS['bg']};
}}
QTabBar::tab {{
    background-color: {COLORS['bg_lighter']};
    color: {COLORS['fg']};
    padding: 6px 12px;
    border: none;
    min-width: 60px;
}}
QTabBar::tab:selected {{
    background-color: {COLORS['bg']};
    color: {COLORS['fg_bright']};
    border-bottom: 2px solid {COLORS['accent']};
}}
QTabBar::tab:hover {{
    background-color: {COLORS['bg_alt']};
}}
QPushButton {{
    background-color: {COLORS['bg_lighter']};
    color: {COLORS['fg']};
    border: 1px solid {COLORS['border']};
    padding: 4px 10px;
    border-radius: 2px;
}}
QPushButton:hover {{
    background-color: {COLORS['accent']};
    color: #ffffff;
}}
QPushButton:pressed {{
    background-color: {COLORS['accent_hover']};
}}
QPushButton:disabled {{
    color: {COLORS['fg_dim']};
    background-color: {COLORS['bg']};
    border-color: {COLORS['bg_lighter']};
}}
QLineEdit {{
    background-color: {COLORS['bg_alt']};
    color: {COLORS['fg']};
    border: 1px solid {COLORS['border']};
    padding: 3px 6px;
    border-radius: 2px;
    selection-background-color: {COLORS['selection']};
}}
QMenuBar {{
    background-color: {COLORS['bg_lighter']};
    color: {COLORS['fg']};
    border: none;
}}
QMenuBar::item:selected {{
    background-color: {COLORS['accent']};
    color: #ffffff;
}}
QMenu {{
    background-color: {COLORS['bg_lighter']};
    color: {COLORS['fg']};
    border: 1px solid {COLORS['border']};
}}
QMenu::item:selected {{
    background-color: {COLORS['accent']};
    color: #ffffff;
}}
QMenu::separator {{
    height: 1px;
    background-color: {COLORS['border']};
    margin: 4px 8px;
}}
QStatusBar {{
    background-color: {COLORS['status_bg']};
    color: {COLORS['status_fg']};
    font-size: 9pt;
}}
QStatusBar QLabel {{
    background-color: {COLORS['status_bg']};
    color: {COLORS['status_fg']};
    padding: 2px 6px;
}}
QScrollBar:vertical {{
    background-color: {COLORS['bg']};
    width: 12px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {COLORS['bg_lighter']};
    min-height: 24px;
    border-radius: 3px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['fg_dim']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background-color: {COLORS['bg']};
    height: 12px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background-color: {COLORS['bg_lighter']};
    min-width: 24px;
    border-radius: 3px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {COLORS['fg_dim']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QLabel {{
    background-color: transparent;
}}
"""


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
class KHUxExplorer(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("KHUx File Explorer")
        self.resize(1400, 850)
        self.setMinimumSize(900, 600)

        # State
        self.entries: List[BGADEntry] = []
        self.entry_map: Dict[str, BGADEntry] = {}
        self.entry_formats: Dict[str, str] = {}
        self.current_entry: Optional[BGADEntry] = None
        self.current_file: Optional[str] = None
        self.recent_files: List[str] = []
        self._tree_items: Dict[str, QTreeWidgetItem] = {}
        self._zoom_level: float = 1.0
        self._current_pil_image: Optional[Any] = None

        self._load_recent_files()
        self._build_menu()
        self._build_ui()
        self._build_status_bar()
        self._bind_shortcuts()

    # -------------------------------------------------------------------
    # Menu
    # -------------------------------------------------------------------
    def _build_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")

        open_action = QAction("Open File...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_file)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        self._recent_menu = file_menu.addMenu("Recent Files")
        self._rebuild_recent_menu()

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _rebuild_recent_menu(self):
        self._recent_menu.clear()
        for path in self.recent_files:
            display = path if len(path) < 60 else "..." + path[-57:]
            action = self._recent_menu.addAction(display)
            # Capture path in lambda via default arg
            action.triggered.connect(lambda checked, p=path: self._load_file(p))
        if not self.recent_files:
            action = self._recent_menu.addAction("(none)")
            action.setEnabled(False)

    # -------------------------------------------------------------------
    # UI Layout
    # -------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(1, 1, 1, 0)
        main_layout.setSpacing(0)

        # 3-pane splitter
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self._splitter)

        # --- LEFT PANE: File tree ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(4, 4, 2, 4)
        left_layout.setSpacing(2)

        # Toolbar row
        toolbar = QHBoxLayout()
        open_btn = QPushButton("Open File")
        open_btn.clicked.connect(self._open_file)
        toolbar.addWidget(open_btn)

        self._file_label = QLabel("No file loaded")
        self._file_label.setStyleSheet(f"color: {COLORS['fg_dim']};")
        toolbar.addWidget(self._file_label, 1)
        left_layout.addLayout(toolbar)

        # Search bar
        search_layout = QHBoxLayout()
        filter_label = QLabel("Filter:")
        search_layout.addWidget(filter_label)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search entries...")
        self._search_edit.textChanged.connect(self._on_filter_changed)
        search_layout.addWidget(self._search_edit, 1)

        clear_btn = QPushButton("X")
        clear_btn.setFixedWidth(28)
        clear_btn.clicked.connect(lambda: self._search_edit.clear())
        search_layout.addWidget(clear_btn)
        left_layout.addLayout(search_layout)

        # Tree widget
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setAnimated(False)
        self.tree.setUniformRowHeights(True)  # Performance for large trees
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree.itemSelectionChanged.connect(self._on_tree_select)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_right_click)
        left_layout.addWidget(self.tree, 1)

        self._splitter.addWidget(left_widget)

        # --- CENTER PANE: Preview ---
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(2, 4, 2, 4)
        center_layout.setSpacing(2)

        # Preview toolbar
        preview_toolbar = QHBoxLayout()

        preview_label = QLabel("Preview")
        preview_label.setStyleSheet(f"font-weight: bold; color: {COLORS['fg_bright']};")
        preview_toolbar.addWidget(preview_label)
        preview_toolbar.addStretch()

        self._zoom_in_btn = QPushButton("+")
        self._zoom_in_btn.setFixedWidth(28)
        self._zoom_in_btn.setEnabled(False)
        self._zoom_in_btn.clicked.connect(self._zoom_in)
        preview_toolbar.addWidget(self._zoom_in_btn)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet(f"color: {COLORS['fg_dim']};")
        preview_toolbar.addWidget(self._zoom_label)

        self._zoom_out_btn = QPushButton("-")
        self._zoom_out_btn.setFixedWidth(28)
        self._zoom_out_btn.setEnabled(False)
        self._zoom_out_btn.clicked.connect(self._zoom_out)
        preview_toolbar.addWidget(self._zoom_out_btn)

        self._export_btn = QPushButton("Export")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_entry)
        preview_toolbar.addWidget(self._export_btn)

        center_layout.addLayout(preview_toolbar)

        # Preview notebook
        self._preview_notebook = QTabWidget()

        # Image tab
        self._image_preview = ImagePreviewWidget()
        self._image_preview.zoom_changed.connect(self._on_zoom_changed)
        self._preview_notebook.addTab(self._image_preview, "Image")

        # Text tab (QTextEdit for HTML support / JSON highlighting)
        self._preview_text = QTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_text.setFont(QFont("Consolas", 10))
        self._preview_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['text_bg']};
                color: {COLORS['fg']};
                border: none;
                padding: 8px;
                selection-background-color: {COLORS['selection']};
            }}
        """)
        self._preview_notebook.addTab(self._preview_text, "Text")

        # Hex dump tab
        self._preview_hex = StyledTextEdit(wrap=False)
        self._preview_notebook.addTab(self._preview_hex, "Hex Dump")

        center_layout.addWidget(self._preview_notebook, 1)
        self._splitter.addWidget(center_widget)

        # --- RIGHT PANE: Properties + Hex ---
        right_notebook = QTabWidget()

        # Properties tab
        self._props_text = PropertiesTextEdit()
        right_notebook.addTab(self._props_text, "Properties")

        # Hex view tab
        self._hex_text = StyledTextEdit(wrap=False)
        right_notebook.addTab(self._hex_text, "Hex View")

        self._splitter.addWidget(right_notebook)

        # Set initial splitter proportions (20% / 50% / 30%)
        QTimer.singleShot(50, self._set_initial_splitter)

    def _set_initial_splitter(self):
        w = self.width()
        self._splitter.setSizes([int(w * 0.20), int(w * 0.50), int(w * 0.30)])

    def _build_status_bar(self):
        self._status_bar = self.statusBar()
        self._status_left = QLabel("Ready")
        self._status_right = QLabel("")
        self._status_bar.addWidget(self._status_left, 1)
        self._status_bar.addPermanentWidget(self._status_right)

    # -------------------------------------------------------------------
    # Shortcuts
    # -------------------------------------------------------------------
    def _bind_shortcuts(self):
        # Ctrl+O is already on the menu action
        focus_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        focus_shortcut.activated.connect(self._focus_search)

        escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        escape_shortcut.activated.connect(lambda: self._search_edit.clear())

    def _focus_search(self):
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    # -------------------------------------------------------------------
    # File operations
    # -------------------------------------------------------------------
    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open KHUx File",
            "",
            "KHUx Files (*.mp4 *.png *.jpg *.gif *.lwf *.bin);;All Files (*.*)",
        )
        if path:
            self._load_file(path)

    def _load_file(self, path: str):
        if not os.path.exists(path):
            QMessageBox.critical(self, "Error", f"File not found:\n{path}")
            return

        self._status_left.setText(f"Loading {os.path.basename(path)}...")
        QApplication.processEvents()

        # Check if it's a standalone file (not a BGAD container)
        with open(path, "rb") as f:
            magic = f.read(4)

        if magic == b"\x89BTF":
            self._load_standalone_btf(path)
            return

        if magic == b"LWF\x00":
            self._load_standalone_file(path, "lwf")
            return

        if magic not in (b"BGAD",):
            # Try as BGAD anyway — might be a renamed container
            pass

        try:
            container = KHUxBGADContainer(path)
            entries = container.iter_entries()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to parse container:\n{e}")
            self._status_left.setText("Ready")
            return

        self.current_file = path
        self.entries = entries

        # Try to resolve mode 3 names via companion BGI
        self._resolve_names_via_bgi(path)

        self.entry_map = {e.name: e for e in entries}

        # Detect formats
        self.entry_formats = {}
        for e in entries:
            if e.data and len(e.data) >= 4:
                self.entry_formats[e.name] = detect_format(e.data[:4])
            else:
                self.entry_formats[e.name] = "unknown"

        # Update recent files
        norm_path = os.path.normpath(path)
        if norm_path in self.recent_files:
            self.recent_files.remove(norm_path)
        self.recent_files.insert(0, norm_path)
        self.recent_files = self.recent_files[:10]
        self._save_recent_files()
        self._rebuild_recent_menu()

        # Update file label
        fname = os.path.basename(path)
        self._file_label.setText(fname)
        self._file_label.setStyleSheet(f"color: {COLORS['fg_bright']};")

        # Build tree
        self._populate_tree()

        # Update status
        self._status_left.setText(f"Loaded {fname}")
        self._status_right.setText(f"{len(entries)} entries")

        # Show container-level properties
        self._show_container_properties()

    def _populate_tree(self, filter_text: str = ""):
        self.tree.clear()
        self._tree_items.clear()

        # Block signals during bulk insert for performance
        self.tree.setUpdatesEnabled(False)
        self.tree.blockSignals(True)

        filter_lower = filter_text.lower()
        folder_nodes: Dict[str, QTreeWidgetItem] = {}

        sorted_entries = sorted(self.entries, key=lambda e: e.name.lower())

        for entry in sorted_entries:
            if filter_lower and filter_lower not in entry.name.lower():
                continue

            parts = entry.name.replace("\\", "/").split("/")
            parts = [p for p in parts if p]
            if not parts:
                parts = [entry.name or "/"]
            fmt = self.entry_formats.get(entry.name, "unknown")
            badge = FORMAT_BADGES.get(fmt, "")

            # Build folder hierarchy
            parent: Optional[QTreeWidgetItem] = None
            for i, part in enumerate(parts[:-1]):
                folder_path = "/".join(parts[:i + 1])
                if folder_path not in folder_nodes:
                    item = QTreeWidgetItem()
                    item.setText(0, f"  {part}")
                    if parent is None:
                        self.tree.addTopLevelItem(item)
                    else:
                        parent.addChild(item)
                    folder_nodes[folder_path] = item
                parent = folder_nodes[folder_path]

            # Leaf entry
            leaf_name = parts[-1]
            display = f"  {badge} {leaf_name}" if badge else f"  {leaf_name}"

            leaf_item = QTreeWidgetItem()
            leaf_item.setText(0, display)
            leaf_item.setData(0, ROLE_ENTRY_NAME, entry.name)
            leaf_item.setData(0, ROLE_FORMAT, fmt)

            # Apply format color
            color = FORMAT_COLORS.get(fmt, COLORS["fg"])
            leaf_item.setForeground(0, QColor(color))

            if parent is None:
                self.tree.addTopLevelItem(leaf_item)
            else:
                parent.addChild(leaf_item)

            self._tree_items[entry.name] = leaf_item

            # If this is a BGI entry, expand with clickable file list
            if HAS_BGI and entry.data[:4] == b'\x89BGI':
                try:
                    buf = _io.BufferedReader(_io.BytesIO(entry.data))
                    try:
                        bgi = KHUxBGI(buf, file_name='index', key=KEY_DOWNLOAD)
                        archive = bgi.parse()
                    except Exception:
                        buf = _io.BufferedReader(_io.BytesIO(entry.data))
                        bgi = KHUxBGI(buf, file_name='index', key=KEY_APK)
                        archive = bgi.parse()

                    num_files = len(archive.names)
                    leaf_item.setText(0, f"  [BGI] {leaf_name} ({num_files} files)")

                    cap = min(num_files, 2000)
                    for ne in archive.names[:cap]:
                        ent = archive.entries[ne.entry_index] if ne.entry_index < len(archive.entries) else None
                        child = QTreeWidgetItem()
                        child.setText(0, f"  {ne.name}")
                        child.setData(0, ROLE_ENTRY_NAME, f"__bgi__{ne.entry_index}")
                        child.setData(0, ROLE_FORMAT, f"{ne.entry_index}|{ent.offset if ent else 0}|{ne.name}")
                        child.setForeground(0, QColor(COLORS["fg_dim"]))
                        leaf_item.addChild(child)

                    if num_files > cap:
                        more = QTreeWidgetItem()
                        more.setText(0, f"  ... and {num_files - cap} more")
                        more.setData(0, ROLE_ENTRY_NAME, None)
                        more.setForeground(0, QColor(COLORS["fg_dim"]))
                        leaf_item.addChild(more)
                except Exception:
                    pass

        self.tree.blockSignals(False)
        self.tree.setUpdatesEnabled(True)

        # Update filtered count in status
        shown = len(self._tree_items)
        total = len(self.entries)
        if filter_text:
            self._status_right.setText(f"{shown}/{total} entries (filtered)")
        else:
            self._status_right.setText(f"{total} entries")

    # -------------------------------------------------------------------
    # Tree interaction
    # -------------------------------------------------------------------
    def _on_filter_changed(self, text: str):
        if self.entries:
            self._populate_tree(text)

    def _on_tree_select(self):
        items = self.tree.selectedItems()
        if not items:
            return

        item = items[0]
        entry_name = item.data(0, ROLE_ENTRY_NAME)
        if entry_name is None:
            return

        # Handle BGI child items (show offset/index in properties)
        if isinstance(entry_name, str) and entry_name.startswith("__bgi__"):
            bgi_info = item.data(0, ROLE_FORMAT)
            if bgi_info:
                parts = bgi_info.split("|", 2)
                idx, offset, name = int(parts[0]), int(parts[1]), parts[2]
                self._props_text.clear()
                self._props_text.append_header("BGI Entry")
                self._props_text.append_separator()
                self._props_text.append_kv("Name", name)
                self._props_text.append_kv("Entry Index", str(idx))
                self._props_text.append_kv("Offset", f"0x{offset:08x} ({offset})")
                self._props_text.moveCursor(QTextCursor.MoveOperation.Start)
            return

        entry = self.entry_map.get(entry_name)
        if entry is None:
            return

        self.current_entry = entry
        self._export_btn.setEnabled(True)

        self._show_entry_properties(entry)
        self._show_hex_view(entry)
        self._show_preview(entry)

    def _on_tree_right_click(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return

        self.tree.setCurrentItem(item)
        self._on_tree_select()

        if self.current_entry is None:
            return

        menu = QMenu(self)
        export_action = menu.addAction("Export Entry...")
        export_action.triggered.connect(self._export_entry)

        export_raw_action = menu.addAction("Export Raw Data...")
        export_raw_action.triggered.connect(self._export_raw)

        menu.addSeparator()

        copy_action = menu.addAction("Copy Name")
        copy_action.triggered.connect(self._copy_entry_name)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # -------------------------------------------------------------------
    # Properties display
    # -------------------------------------------------------------------
    def _show_container_properties(self):
        self._props_text.clear()

        self._props_text.append_header("Container Info")
        self._props_text.append_separator()

        if self.current_file:
            self._props_text.append_kv("File", os.path.basename(self.current_file))
            self._props_text.append_kv("Path", self.current_file)
            self._props_text.append_kv("Size", _format_size(os.path.getsize(self.current_file)))
        self._props_text.append_kv("Entries", str(len(self.entries)))

        # Format distribution
        fmt_counts: Dict[str, int] = {}
        for fmt in self.entry_formats.values():
            fmt_counts[fmt] = fmt_counts.get(fmt, 0) + 1

        if fmt_counts:
            self._props_text.append_header("\nFormat Distribution")
            self._props_text.append_separator()
            for fmt, count in sorted(fmt_counts.items(), key=lambda x: -x[1]):
                self._props_text.append_kv(fmt.upper(), str(count))

        # First entry header
        if self.entries:
            hdr = self.entries[0].header
            self._props_text.append_header("\nContainer Header (first entry)")
            self._props_text.append_separator()
            self._props_text.append_kv("Magic", hdr.magic.decode("ascii", errors="replace"))
            self._props_text.append_kv("Version", str(hdr.version))
            self._props_text.append_kv("Flags", f"0x{hdr.flags:04x}")
            self._props_text.append_kv("Encryption Mode", str(hdr.encryption_mode))
            self._props_text.append_kv("Compression Mode", str(hdr.compression_mode))

        # Avatar info
        if HAS_AVATAR and self._is_avatar_container():
            try:
                avatar_data = KHUxAvatar.from_bgad_entries(self.entries)
                self._props_text.append_header("\nAvatar Info")
                self._props_text.append_separator()
                self._props_text.append_kv("Total Parts", str(avatar_data.total_count))
                self._props_text.append_kv("Hash", avatar_data.hash)
                self._props_text.append_kv("Loaded Parts", str(len(avatar_data.parts)))
            except Exception:
                pass

        # Scroll to top
        self._props_text.moveCursor(QTextCursor.MoveOperation.Start)

    def _show_entry_properties(self, entry: BGADEntry):
        self._props_text.clear()

        fmt = self.entry_formats.get(entry.name, "unknown")

        self._props_text.append_header("Entry Info")
        self._props_text.append_separator()

        self._props_text.append_kv("Name", entry.name)
        self._props_text.append_kv("Format", fmt.upper())
        self._props_text.append_kv("Data Size", _format_size(len(entry.data)))
        self._props_text.append_kv("Offset", f"0x{entry.offset:08x}")

        # BGAD Header
        hdr = entry.header
        self._props_text.append_header("\nBGAD Header")
        self._props_text.append_separator()

        self._props_text.append_kv("Magic", hdr.magic.decode("ascii", errors="replace"))
        self._props_text.append_kv("Version", str(hdr.version))
        self._props_text.append_kv("Flags", f"0x{hdr.flags:04x}")
        self._props_text.append_kv("Header Size", str(hdr.header_size))
        self._props_text.append_kv("Name Length", str(hdr.name_length))
        self._props_text.append_kv("Encryption Mode", str(hdr.encryption_mode))
        self._props_text.append_kv("Compression Mode", str(hdr.compression_mode))
        self._props_text.append_kv("Data Size", _format_size(hdr.data_size))
        self._props_text.append_kv("Decompressed Size", _format_size(hdr.decompressed_size))

        if hdr.compression_mode > 0 and hdr.decompressed_size > 0:
            ratio = hdr.data_size / hdr.decompressed_size * 100 if hdr.decompressed_size else 0
            self._props_text.append_kv("Compression Ratio", f"{ratio:.1f}%")

        # Format-specific info
        if fmt == "btf" and HAS_BTF:
            self._show_btf_properties(entry)
        elif fmt in ("plist", "json"):
            self._show_text_properties(entry)

        # BGI index display
        if HAS_BGI and entry.data[:4] == b'\x89BGI':
            self._show_bgi_index_properties(entry)

        # Avatar part info (master data decryption)
        if HAS_AVATAR and self._is_avatar_container() and entry.name.isdigit():
            self._show_avatar_entry_properties(entry)

        # Master data decryption for numbered entries in master containers
        if HAS_MASTER_DATA and self._is_master_data_container() and entry.name.isdigit():
            self._show_master_data_properties(entry)

        self._props_text.moveCursor(QTextCursor.MoveOperation.Start)

    def _show_btf_properties(self, entry: BGADEntry):
        try:
            btf = KHUxBTF.from_bytes(entry.data)
            hdr = btf.header

            self._props_text.append_header("\nBTF Header")
            self._props_text.append_separator()

            self._props_text.append_kv("Image Size", f"{hdr.image_width} x {hdr.image_height}")
            self._props_text.append_kv("Canvas Size", f"{hdr.canvas_width} x {hdr.canvas_height}")
            self._props_text.append_kv("Canvas Offset", f"({hdr.canvas_offset_x}, {hdr.canvas_offset_y})")

            if hdr.image_format == hdr.FORMAT_RGBA:
                fmt_str = "RGBA (0x{:06x})".format(hdr.image_format)
            elif hdr.image_format == hdr.FORMAT_INDEXED:
                fmt_str = "Indexed (0x{:06x})".format(hdr.image_format)
            else:
                fmt_str = f"0x{hdr.image_format:06x}"
            self._props_text.append_kv("Image Format", fmt_str)

        except Exception as e:
            self._props_text.append_dim(f"\n[BTF parse error: {e}]")

    def _show_text_properties(self, entry: BGADEntry):
        try:
            text = entry.data.decode("utf-8", errors="replace")
            lines = text.count("\n") + 1
            self._props_text.append_header("\nText Info")
            self._props_text.append_separator()
            self._props_text.append_kv("Lines", str(lines))
            self._props_text.append_kv("Characters", str(len(text)))
        except Exception:
            pass

    def _is_avatar_container(self) -> bool:
        names = {e.name for e in self.entries}
        return "avatarParts" in names or "hash" in names

    def _show_avatar_entry_properties(self, entry: BGADEntry):
        try:
            avatar_data = KHUxAvatar.from_bgad_entries(self.entries)
            part_id = int(entry.name)
            for part in avatar_data.parts:
                if part.id == part_id:
                    self._props_text.append_header("\nAvatar Part")
                    self._props_text.append_separator()
                    self._props_text.append_kv("Part ID", str(part.id))
                    self._props_text.append_kv("Timestamp", str(part.timestamp))
                    self._props_text.append_kv("Payload Size", _format_size(part.payload_size))
                    break
        except Exception:
            pass

    def _show_bgi_index_properties(self, entry: BGADEntry):
        """Parse a BGI index entry and display the name list with offsets."""
        try:
            buf = _io.BufferedReader(_io.BytesIO(entry.data))
            try:
                bgi = KHUxBGI(buf, file_name='index', key=KEY_DOWNLOAD)
                archive = bgi.parse()
            except Exception:
                buf = _io.BufferedReader(_io.BytesIO(entry.data))
                bgi = KHUxBGI(buf, file_name='index', key=KEY_APK)
                archive = bgi.parse()

            import struct as _struct
            flags = _struct.unpack_from("<I", entry.data, 8)[0]

            self._props_text.append_header("\nBGI Index")
            self._props_text.append_separator()
            self._props_text.append_kv("Version", str(_struct.unpack_from("<I", entry.data, 4)[0]))
            self._props_text.append_kv("Encrypted", "Yes" if flags & 1 else "No")
            self._props_text.append_kv("Total Names", str(len(archive.names)))
            self._props_text.append_kv("Total Entries", str(len(archive.entries)))

            self._props_text.append_header("\nFile List")
            self._props_text.append_separator()

            cap = min(len(archive.names), 500)
            for i, ne in enumerate(archive.names[:cap]):
                ent = archive.entries[ne.entry_index] if ne.entry_index < len(archive.entries) else None
                offset_str = f"0x{ent.offset:08x}" if ent else "?"
                self._props_text.append_dim(
                    f"  [{ne.entry_index:5d}] {offset_str}  {ne.name}"
                )

            if len(archive.names) > cap:
                self._props_text.append_dim(
                    f"\n  ... and {len(archive.names) - cap} more entries"
                )
        except Exception as e:
            self._props_text.append_dim(f"\n[BGI parse error: {e}]")

    def _is_master_data_container(self) -> bool:
        """Check if container looks like a master data table (type + hash + numbered entries)."""
        if len(self.entries) < 3:
            return False
        has_hash = any(e.name == "hash" for e in self.entries)
        has_numbered = any(e.name.isdigit() for e in self.entries)
        first_not_special = self.entries[0].name not in ("/", "md5", "size", "hash", "revision")
        return has_hash and has_numbered and first_not_special

    def _get_master_table_type(self) -> str:
        """Get the table type name from the first entry."""
        if self.entries:
            name = self.entries[0].name
            if name not in ("/", "md5", "size", "hash") and not name.isdigit():
                return name
        return ""

    def _show_master_data_properties(self, entry: BGADEntry):
        """Decrypt and display master data for a numbered entry."""
        if len(entry.data) < 8:
            return

        # If this is an avatar container, show full avatar part struct
        if HAS_AVATAR and self._is_avatar_container():
            try:
                part = KHUxAvatar.decrypt_part(entry.data)
                self._props_text.append_header("\nDecrypted Avatar Part")
                self._props_text.append_separator()
                self._props_text.append_kv("Avatar Parts ID", str(part.avatar_parts_id))
                self._props_text.append_kv("Name", part.name)
                self._props_text.append_kv("Parts Type", f"{part.parts_type} ({part.parts_type_name})")
                self._props_text.append_kv("Gender", str(part.gender)
                                           + (" (Male)" if part.is_male else " (Female)" if part.is_female else ""))
                self._props_text.append_kv("Combination Type", str(part.combination_type))
                self._props_text.append_kv("Combination Flag", str(part.combination_flag))
                self._props_text.append_kv("Position", str(part.position))
                self._props_text.append_kv("Lux Category", str(part.lux_category))
                self._props_text.append_kv("Lux Add Rate", str(part.lux_add_rate))
                self._props_text.append_kv("Set Kind", str(part.set_kind))
                self._props_text.append_kv("Fixed", "Yes" if part.is_fixed else "No")
                self._props_text.append_kv("Active", "Yes" if part.is_active else "No")
                if part.valid_set_cloth > 0:
                    cloth_ids = part.set_cloth[:part.valid_set_cloth]
                    self._props_text.append_kv("Set Cloth", ", ".join(str(c) for c in cloth_ids))
                return
            except Exception:
                pass  # Fall through to generic master data

        # Generic master data decryption
        try:
            import struct as _struct
            seed, psize, decrypted = decrypt_master_data_payload(entry.data)

            table_type = self._get_master_table_type()
            self._props_text.append_header(f"\nDecrypted: {table_type}")
            self._props_text.append_separator()

            if len(decrypted) >= 4:
                rec_id = _struct.unpack_from("<i", decrypted, 0)[0]
                self._props_text.append_kv("Record ID", str(rec_id))

            if len(decrypted) >= 8:
                raw_name = decrypted[4:min(134, len(decrypted))]
                null = raw_name.find(0)
                if null >= 0:
                    raw_name = raw_name[:null]
                try:
                    name_str = raw_name.decode("utf-8")
                    if name_str and all(c.isprintable() or c == ' ' for c in name_str):
                        self._props_text.append_kv("Name", name_str)
                except (UnicodeDecodeError, ValueError):
                    pass

            self._props_text.append_kv("Table Type", table_type)
            self._props_text.append_kv("Seed", f"0x{seed:08x}")
            self._props_text.append_kv("Payload Size", _format_size(psize))

            try:
                text = decrypted.decode("utf-8")
                self._props_text.append_kv("Content", "Text/UTF-8")
                preview = text[:200] + ("..." if len(text) > 200 else "")
                self._props_text.append_dim(f"\n{preview}")
            except UnicodeDecodeError:
                self._props_text.append_kv("Content", "Binary struct")
                self._props_text.append_dim(f"\n{_hex_dump(decrypted, length=128)}")
        except Exception as e:
            self._props_text.append_dim(f"\n[Master data decrypt error: {e}]")

    # -------------------------------------------------------------------
    # Hex view
    # -------------------------------------------------------------------
    def _show_hex_view(self, entry: BGADEntry):
        self._hex_text.setPlainText(_hex_dump(entry.data, length=256))

    # -------------------------------------------------------------------
    # Preview
    # -------------------------------------------------------------------
    def _show_preview(self, entry: BGADEntry):
        fmt = self.entry_formats.get(entry.name, "unknown")

        # Clear all previews
        self._image_preview.clear_image()
        self._preview_text.clear()
        self._preview_hex.clear()
        self._current_pil_image = None
        self._zoom_level = 1.0
        self._zoom_label.setText("100%")

        if fmt == "btf" and HAS_BTF and HAS_PIL:
            self._show_btf_preview(entry)
            self._preview_notebook.setCurrentIndex(0)  # Image tab
            self._zoom_in_btn.setEnabled(True)
            self._zoom_out_btn.setEnabled(True)
        elif fmt in ("plist", "json") or self._is_text_data(entry.data):
            self._show_text_preview(entry)
            self._preview_notebook.setCurrentIndex(1)  # Text tab
            self._zoom_in_btn.setEnabled(False)
            self._zoom_out_btn.setEnabled(False)
        elif HAS_MASTER_DATA and self._is_master_data_container() and entry.name.isdigit() and len(entry.data) >= 8:
            # Try to decrypt master data and show as text preview
            self._show_master_data_preview(entry)
            self._zoom_in_btn.setEnabled(False)
            self._zoom_out_btn.setEnabled(False)
        else:
            self._show_hex_preview(entry)
            self._preview_notebook.setCurrentIndex(2)  # Hex dump tab
            self._zoom_in_btn.setEnabled(False)
            self._zoom_out_btn.setEnabled(False)

    def _show_btf_preview(self, entry: BGADEntry):
        try:
            btf = KHUxBTF.from_bytes(entry.data)
            img = btf.decode(use_canvas=True)
            self._current_pil_image = img

            pixmap = _pil_image_to_qpixmap(img)
            self._image_preview.set_pixmap(pixmap)

        except Exception as e:
            self._image_preview.show_error(f"BTF decode error: {e}")

    @staticmethod
    def _truncate_json(obj, depth: int = 0, max_depth: int = 3):
        """Truncate nested JSON objects/arrays beyond max_depth."""
        if depth >= max_depth:
            if isinstance(obj, dict):
                return "{...}"
            elif isinstance(obj, list):
                return "[...]"
        if isinstance(obj, dict):
            return {k: KHUxExplorer._truncate_json(v, depth + 1, max_depth) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [KHUxExplorer._truncate_json(v, depth + 1, max_depth) for v in obj]
        return obj

    @staticmethod
    def _json_to_html(text: str) -> str:
        """Convert pretty-printed JSON text to syntax-highlighted HTML."""
        import html as _html
        lines = text.split("\n")
        html_lines = []
        for line in lines:
            stripped = line.lstrip()
            indent = _html.escape(line[:len(line) - len(stripped)])
            result_parts = []
            i = 0
            s = stripped
            while i < len(s):
                ch = s[i]
                if ch == '"':
                    # Find end of string
                    j = i + 1
                    while j < len(s):
                        if s[j] == '\\':
                            j += 2
                            continue
                        if s[j] == '"':
                            j += 1
                            break
                        j += 1
                    token = s[i:j]
                    escaped = _html.escape(token)
                    # Check if this is a key (followed by ':')
                    rest = s[j:].lstrip()
                    if rest.startswith(":"):
                        result_parts.append(f'<span style="color:#9CDCFE">{escaped}</span>')
                    else:
                        result_parts.append(f'<span style="color:#CE9178">{escaped}</span>')
                    i = j
                elif ch in '0123456789' or (ch == '-' and i + 1 < len(s) and s[i + 1] in '0123456789'):
                    # Number
                    j = i + 1
                    while j < len(s) and s[j] in '0123456789.eE+-':
                        j += 1
                    token = s[i:j]
                    result_parts.append(f'<span style="color:#B5CEA8">{_html.escape(token)}</span>')
                    i = j
                elif s[i:i+4] in ('true', 'null') or s[i:i+5] == 'false':
                    length = 5 if s[i:i+5] == 'false' else 4
                    token = s[i:i+length]
                    result_parts.append(f'<span style="color:#569CD6">{_html.escape(token)}</span>')
                    i += length
                elif s[i:i+5] == '{...}' or s[i:i+5] == '[...]':
                    token = s[i:i+5]
                    result_parts.append(f'<span style="color:#808080">{_html.escape(token)}</span>')
                    i += 5
                else:
                    result_parts.append(_html.escape(ch))
                    i += 1
            html_lines.append(indent + "".join(result_parts))
        return "<br>".join(html_lines)

    def _show_text_preview(self, entry: BGADEntry):
        try:
            text = entry.data.decode("utf-8", errors="replace")

            # Pretty-print JSON: explicit json format, .json extension, or content that looks like JSON
            fmt = self.entry_formats.get(entry.name, "unknown")
            stripped = text.lstrip()
            is_json_content = stripped.startswith(("{", "[{", "["))
            is_json = fmt == "json" or entry.name.endswith(".json") or is_json_content

            if is_json:
                try:
                    obj = json.loads(text)
                    truncated = self._truncate_json(obj, depth=0, max_depth=3)
                    pretty = json.dumps(truncated, indent=2, ensure_ascii=False)
                    html = self._json_to_html(pretty)
                    self._preview_text.setHtml(
                        f'<pre style="font-family:Consolas;font-size:10pt;color:{COLORS["fg"]};'
                        f'background-color:{COLORS["text_bg"]};margin:0;white-space:pre-wrap;">'
                        f'{html}</pre>'
                    )
                    return
                except (json.JSONDecodeError, ValueError):
                    pass

            self._preview_text.setPlainText(text)
        except Exception as e:
            self._preview_text.setPlainText(f"Decode error: {e}")

    def _show_hex_preview(self, entry: BGADEntry):
        self._preview_hex.setPlainText(_hex_dump(entry.data, length=4096))

    def _show_master_data_preview(self, entry: BGADEntry):
        """Decrypt master data and show decrypted content in text or hex preview."""
        try:
            seed, psize, decrypted = decrypt_master_data_payload(entry.data)
            # Try to show as text (possibly JSON)
            try:
                text = decrypted.decode("utf-8")
                stripped = text.lstrip()
                if stripped.startswith(("{", "[{", "[")):
                    try:
                        obj = json.loads(text)
                        truncated = self._truncate_json(obj, depth=0, max_depth=3)
                        pretty = json.dumps(truncated, indent=2, ensure_ascii=False)
                        html = self._json_to_html(pretty)
                        self._preview_text.setHtml(
                            f'<pre style="font-family:Consolas;font-size:10pt;color:{COLORS["fg"]};'
                            f'background-color:{COLORS["text_bg"]};margin:0;white-space:pre-wrap;">'
                            f'{html}</pre>'
                        )
                    except (json.JSONDecodeError, ValueError):
                        self._preview_text.setPlainText(text)
                else:
                    self._preview_text.setPlainText(text)
                self._preview_notebook.setCurrentIndex(1)  # Text tab
            except UnicodeDecodeError:
                self._preview_hex.setPlainText(
                    f"Decrypted master data (seed=0x{seed:08x}, size={psize}):\n\n"
                    + _hex_dump(decrypted, length=4096)
                )
                self._preview_notebook.setCurrentIndex(2)  # Hex dump tab
        except Exception:
            self._show_hex_preview(entry)
            self._preview_notebook.setCurrentIndex(2)

    def _is_text_data(self, data: bytes) -> bool:
        if len(data) == 0:
            return False
        sample = data[:512]
        try:
            sample.decode("utf-8")
            return True
        except UnicodeDecodeError:
            printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13))
            return printable / len(sample) > 0.85

    # -------------------------------------------------------------------
    # Zoom
    # -------------------------------------------------------------------
    def _zoom_in(self):
        self._zoom_level = self._image_preview.zoom_in()
        self._zoom_label.setText(f"{int(self._zoom_level * 100)}%")

    def _zoom_out(self):
        self._zoom_level = self._image_preview.zoom_out()
        self._zoom_label.setText(f"{int(self._zoom_level * 100)}%")

    def _on_zoom_changed(self, level: float):
        self._zoom_level = level
        self._zoom_label.setText(f"{int(level * 100)}%")

    # -------------------------------------------------------------------
    # Export
    # -------------------------------------------------------------------
    def _export_entry(self):
        if self.current_entry is None:
            return

        entry = self.current_entry
        default_name = entry.name.replace("/", "_").replace("\\", "_")
        fmt = self.entry_formats.get(entry.name, "unknown")

        if fmt == "btf" and HAS_BTF and HAS_PIL:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Entry",
                os.path.splitext(default_name)[0] + ".png",
                "PNG Image (*.png);;Raw Data (*.*)",
            )
            if path:
                if path.lower().endswith(".png"):
                    try:
                        btf = KHUxBTF.from_bytes(entry.data)
                        img = btf.decode(use_canvas=True)
                        img.save(path, "PNG")
                        self._status_left.setText(f"Exported: {os.path.basename(path)}")
                    except Exception as e:
                        QMessageBox.critical(self, "Export Error", str(e))
                else:
                    self._write_raw(path, entry.data)
        else:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Entry",
                default_name,
            )
            if path:
                self._write_raw(path, entry.data)

    def _export_raw(self):
        if self.current_entry is None:
            return

        entry = self.current_entry
        default_name = entry.name.replace("/", "_").replace("\\", "_")

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Raw Data",
            default_name,
        )
        if path:
            self._write_raw(path, entry.data)

    def _write_raw(self, path: str, data: bytes):
        try:
            dirname = os.path.dirname(path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            self._status_left.setText(f"Exported: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _copy_entry_name(self):
        if self.current_entry:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.current_entry.name)
            self._status_left.setText(f"Copied: {self.current_entry.name}")

    # -------------------------------------------------------------------
    # Recent files persistence
    # -------------------------------------------------------------------
    def _resolve_names_via_bgi(self, path: str):
        """For .mp4 containers, try loading the companion .png BGI to resolve names."""
        if not path.lower().endswith(".mp4"):
            return
        if not self.entries:
            return
        # Resolve if mode 3 (encrypted names) or if names look like hashes (hex-only, long)
        first_name = self.entries[0].name
        needs_resolve = (
            self.entries[0].header.encryption_mode == 3
            or (len(first_name) >= 20 and all(c in "0123456789abcdef" for c in first_name))
        )
        if not needs_resolve:
            return
        if not HAS_BGI:
            return

        png_path = path[:-4] + ".png"
        if not os.path.exists(png_path):
            return

        try:
            import io
            png_container = KHUxBGADContainer(png_path)
            png_entries = png_container.iter_entries()
            bgi_data = None
            for pe in png_entries:
                if pe.data[:4] == b"\x89BGI":
                    bgi_data = pe.data
                    break
            if not bgi_data:
                return

            from khux.utils.crypto import KEY_APK, KEY_DOWNLOAD
            archive = None
            for key in [KEY_APK, KEY_DOWNLOAD]:
                try:
                    bgi = KHUxBGI(
                        io.BufferedReader(io.BytesIO(bgi_data)),
                        file_name="index", key=key,
                    )
                    archive = bgi.parse()
                    if archive.names:
                        break
                except Exception:
                    archive = None

            if not archive or not archive.names:
                return

            offset_to_name = {}
            for ne in archive.names:
                if ne.entry_index < len(archive.entries):
                    offset_to_name[archive.entries[ne.entry_index].offset] = ne.name

            resolved = 0
            for entry in self.entries:
                bgi_name = offset_to_name.get(entry.offset)
                if bgi_name:
                    entry.name = bgi_name
                    resolved += 1

            if resolved > 0:
                self._status_left.setText(
                    f"Resolved {resolved} names from BGI index"
                )

        except Exception:
            pass

    def _load_standalone_btf(self, path: str):
        """Load a standalone BTF image file (not inside a BGAD container)."""
        with open(path, "rb") as f:
            data = f.read()

        fname = os.path.basename(path)
        dummy_header = BGADHeader(
            magic=b"BGAD", version=2, flags=0, header_size=24,
            name_length=len(fname), encryption_mode=0, compression_mode=0,
            data_size=len(data), decompressed_size=len(data),
        )
        entry = BGADEntry(offset=0, name=fname, data=data, header=dummy_header)

        self.current_file = path
        self.entries = [entry]
        self.entry_map = {entry.name: entry}
        self.entry_formats = {entry.name: "btf"}

        norm_path = os.path.normpath(path)
        if norm_path in self.recent_files:
            self.recent_files.remove(norm_path)
        self.recent_files.insert(0, norm_path)
        self.recent_files = self.recent_files[:10]
        self._save_recent_files()
        self._rebuild_recent_menu()

        self._file_label.setText(fname)
        self._file_label.setStyleSheet(f"color: {COLORS['fg_bright']};")
        self._populate_tree()
        self._status_left.setText(f"Loaded {fname}")
        self._status_right.setText("1 entry (standalone BTF)")

        self.tree.expandAll()
        if self.tree.topLevelItemCount() > 0:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _load_standalone_file(self, path: str, fmt: str):
        """Load a standalone non-BGAD file."""
        with open(path, "rb") as f:
            data = f.read()

        fname = os.path.basename(path)
        dummy_header = BGADHeader(
            magic=b"BGAD", version=2, flags=0, header_size=24,
            name_length=len(fname), encryption_mode=0, compression_mode=0,
            data_size=len(data), decompressed_size=len(data),
        )
        entry = BGADEntry(offset=0, name=fname, data=data, header=dummy_header)

        self.current_file = path
        self.entries = [entry]
        self.entry_map = {entry.name: entry}
        self.entry_formats = {entry.name: fmt}

        norm_path = os.path.normpath(path)
        if norm_path in self.recent_files:
            self.recent_files.remove(norm_path)
        self.recent_files.insert(0, norm_path)
        self.recent_files = self.recent_files[:10]
        self._save_recent_files()
        self._rebuild_recent_menu()

        self._file_label.setText(fname)
        self._file_label.setStyleSheet(f"color: {COLORS['fg_bright']};")
        self._populate_tree()
        self._status_left.setText(f"Loaded {fname}")
        self._status_right.setText(f"1 entry (standalone {fmt.upper()})")

        self.tree.expandAll()
        if self.tree.topLevelItemCount() > 0:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _recent_file_path(self) -> str:
        return os.path.join(".cache", "recent_files.json")

    def _load_recent_files(self):
        path = self._recent_file_path()
        try:
            if os.path.exists(path):
                with open(path, "r") as f:
                    self.recent_files = json.load(f)
        except Exception:
            self.recent_files = []

    def _save_recent_files(self):
        path = self._recent_file_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(self.recent_files, f, indent=2)
        except Exception:
            pass


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)
    app.setStyle("Fusion")  # Consistent cross-platform base style

    window = KHUxExplorer()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
