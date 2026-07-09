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
from PyQt6.QtCore import Qt, QSize, QTimer, QThread, pyqtSignal
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
    from PIL import Image, ImageDraw, ImageFont
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

try:
    from khux.formats.master import MasterDataParser
    _master_parser = MasterDataParser()
    HAS_MASTER_PARSER = True
except ImportError:
    HAS_MASTER_PARSER = False


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
    "ui":      "#4fc1e9",
    "text":    "#d4d4d4",
    "ttf":     "#e0a050",
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
    "json":    "[JSON]",
    "text":    "[TXT]",
    "ttf":     "[TTF]",
    "stg":     "[STG]",
    "map":     "[MAP]",
    "bgi":     "[BGI]",
    "bgad":    "[BGAD]",
    "jmp":     "[JMP]",
    "bmi":     "[BMI]",
    "cls":     "[CLS]",
    "chp":     "[CHP]",
    "ui":      "[UI]",
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


def _decode_lwf_tex_name(name: str) -> str:
    """Decode hex-encoded LWF texture names like 'atk1_68696b6172692e706e67.png' → 'atk1/hikari.png'."""
    import re as _re
    m = _re.match(r'^(.+?)_([0-9a-f]{6,})\.(\w+)$', name)
    if m:
        prefix, hexpart, _ext = m.groups()
        try:
            decoded = bytes.fromhex(hexpart).decode('utf-8')
            return f"{prefix}/{decoded}"
        except (ValueError, UnicodeDecodeError):
            pass
    return name


def _parse_lwf_data(data: bytes) -> dict:
    """Parse LWF binary and extract metadata, string table, and texture references."""
    import struct as _st
    info = {'strings': [], 'textures': [], 'texture_resolved': {}, 'counts': {}}

    if len(data) < 16:
        return info

    version = _st.unpack_from('<I', data, 4)[0]
    info['version'] = version
    info['version_str'] = f"{(version >> 16) & 0xFF}.{(version >> 8) & 0xFF}.{version & 0xFF}"
    info['data_size'] = _st.unpack_from('<I', data, 8)[0]
    info['total_size'] = _st.unpack_from('<I', data, 12)[0]

    if len(data) < 0x20:
        return info

    info['name_id'] = _st.unpack_from('<I', data, 0x10)[0]
    info['string_byte_length'] = _st.unpack_from('<I', data, 0x14)[0]
    info['animation_byte_length'] = _st.unpack_from('<I', data, 0x18)[0]

    count_fields = [
        (0x1C, 'translate'), (0x24, 'matrix'), (0x2C, 'color'),
        (0x44, 'object'), (0x4C, 'texture'), (0x54, 'textureFragment'),
        (0x5C, 'bitmap'), (0x64, 'bitmapEx'), (0x6C, 'font'),
        (0x8C, 'graphicObject'), (0x9C, 'movieClip'), (0xAC, 'action'),
        (0xB4, 'button'), (0xBC, 'label'), (0xC4, 'instanceName'),
        (0xCC, 'event'), (0xF4, 'frame'), (0xFC, 'movie'),
        (0x104, 'movieLinkage'), (0x10C, 'string'),
    ]

    for offset, name in count_fields:
        if offset + 4 <= len(data):
            info['counts'][name] = _st.unpack_from('<I', data, offset)[0]

    # GREE LWF header: 324 bytes for all versions, 340 for v0x141211+
    header_size = 340 if version >= 0x141211 else 324

    string_byte_len = info['string_byte_length']
    if string_byte_len > 0 and header_size + string_byte_len <= len(data):
        string_data = data[header_size:header_size + string_byte_len]
        strings = []
        for p in string_data.split(b'\x00'):
            if p:
                try:
                    s = p.decode('utf-8')
                    if s and any(c.isprintable() for c in s):
                        strings.append(s)
                except (UnicodeDecodeError, ValueError):
                    pass
        info['strings'] = strings
    else:
        strings = []
        current = bytearray()
        for b in data[16:]:
            if 32 <= b < 127:
                current.append(b)
            else:
                if b == 0 and len(current) >= 3:
                    strings.append(current.decode('ascii'))
                current = bytearray()
        info['strings'] = strings

    img_exts = ('.png', '.btf', '.jpg', '.pvr', '.webp')
    texture_set = set()
    for s in info['strings']:
        if any(s.lower().endswith(ext) for ext in img_exts):
            texture_set.add(s)
    info['textures'] = sorted(texture_set)

    resolved = {}
    for t in info['textures']:
        resolved[t] = _decode_lwf_tex_name(t)
    info['texture_resolved'] = resolved

    return info


def _detect_cocostudio(obj) -> bool:
    """Check if a parsed JSON object is a CocoStudio layout."""
    if not isinstance(obj, dict):
        return False
    if 'widgetTree' in obj:
        return True
    if 'classname' in obj and 'children' in obj:
        return True
    if 'nodeTree' in obj:
        return True
    if 'armature_data' in obj:
        return True
    if 'Content' in obj and isinstance(obj['Content'], dict):
        inner = obj['Content']
        if 'Content' in inner or 'classname' in inner:
            return True
    if 'gameobjects' in obj:
        return True
    return False


def _cs_get_root(obj):
    """Extract root widget node from any CocoStudio format version."""
    if 'widgetTree' in obj:
        return obj['widgetTree']
    if 'nodeTree' in obj:
        return obj['nodeTree']
    if 'gameobjects' in obj:
        return obj
    if 'Content' in obj and 'classname' not in obj:
        inner = obj['Content']
        if isinstance(inner, dict) and 'Content' in inner and 'classname' not in inner:
            return inner['Content']
        return inner
    return obj


def _cs_widget_props(node):
    """Extract widget properties from either v1.x or v2.x CocoStudio format."""
    opts = node.get('options', node)
    # v1.x: options.x/y, options.width/height, options.anchorPointX/Y, options.fileNameData.path
    # v2.x: Position.X/Y, Size.X/Y, AnchorPoint.ScaleX/Y, FileData.Path
    x = float(opts.get('x', 0)) if 'x' in opts else float(opts.get('Position', {}).get('X', 0))
    y = float(opts.get('y', 0)) if 'y' in opts else float(opts.get('Position', {}).get('Y', 0))
    w = int(opts.get('width', 0)) if 'width' in opts else int(opts.get('Size', {}).get('X', 0))
    h = int(opts.get('height', 0)) if 'height' in opts else int(opts.get('Size', {}).get('Y', 0))
    ax = float(opts.get('anchorPointX', 0.5)) if 'anchorPointX' in opts else float(opts.get('AnchorPoint', {}).get('ScaleX', 0.5))
    ay = float(opts.get('anchorPointY', 0.5)) if 'anchorPointY' in opts else float(opts.get('AnchorPoint', {}).get('ScaleY', 0.5))

    tex_path = None
    for key in ('fileNameData', 'normalData', 'backGroundImageData', 'FileData'):
        fnd = opts.get(key, {})
        if isinstance(fnd, dict):
            p = fnd.get('path') or fnd.get('Path')
            if p:
                tex_path = p
                break

    s9 = bool(opts.get('scale9Enable', False))
    s9_x = int(opts.get('capInsetsX', 0))
    s9_y = int(opts.get('capInsetsY', 0))
    s9_w = int(opts.get('capInsetsWidth', 0))
    s9_h = int(opts.get('capInsetsHeight', 0))

    cn = node.get('classname', '?')
    nm = opts.get('name', node.get('name', ''))

    return x, y, w, h, ax, ay, tex_path, cn, nm, s9, s9_x, s9_y, s9_w, s9_h


def _cs_bounding_box(node, px=0, py=0, show_hidden=False):
    """Compute the bounding box of widgets in the tree. Returns (min_x, min_y, max_x, max_y) in cocos2d world coords."""
    if not isinstance(node, dict):
        return (px, py, px, py)
    opts = node.get('options', node)
    if not show_hidden and not opts.get('visible', True):
        return (px, py, px, py)
    x, y, w, h, ax, ay, *_ = _cs_widget_props(node)
    awx = px + x
    awy = py + y
    bl_x = awx - w * ax
    bl_y = awy - h * ay
    min_x, min_y = bl_x, bl_y
    max_x, max_y = bl_x + w, bl_y + h
    for child in node.get('children', []):
        cx1, cy1, cx2, cy2 = _cs_bounding_box(child, awx, awy, show_hidden)
        min_x = min(min_x, cx1)
        min_y = min(min_y, cy1)
        max_x = max(max_x, cx2)
        max_y = max(max_y, cy2)
    return (min_x, min_y, max_x, max_y)


def _scale9_resize(img, tw, th, cx, cy, cw, ch):
    """9-slice scale: corners fixed, edges stretch one axis, center stretches both."""
    sw, sh = img.size
    if cw <= 0 or ch <= 0:
        cw, ch = max(1, sw - 2), max(1, sh - 2)
        cx, cy = 1, 1
    left, right = cx, sw - cx - cw
    top, bottom = cy, sh - cy - ch
    mid_w = max(1, tw - left - right)
    mid_h = max(1, th - top - bottom)
    result = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    if left > 0 and top > 0:
        result.paste(img.crop((0, 0, left, top)), (0, 0))
    if right > 0 and top > 0:
        result.paste(img.crop((sw - right, 0, sw, top)), (tw - right, 0))
    if left > 0 and bottom > 0:
        result.paste(img.crop((0, sh - bottom, left, sh)), (0, th - bottom))
    if right > 0 and bottom > 0:
        result.paste(img.crop((sw - right, sh - bottom, sw, sh)), (tw - right, th - bottom))
    if top > 0:
        result.paste(img.crop((left, 0, sw - right, top)).resize((mid_w, top), Image.LANCZOS), (left, 0))
    if bottom > 0:
        result.paste(img.crop((left, sh - bottom, sw - right, sh)).resize((mid_w, bottom), Image.LANCZOS), (left, th - bottom))
    if left > 0:
        result.paste(img.crop((0, top, left, sh - bottom)).resize((left, mid_h), Image.LANCZOS), (0, top))
    if right > 0:
        result.paste(img.crop((sw - right, top, sw, sh - bottom)).resize((right, mid_h), Image.LANCZOS), (tw - right, top))
    result.paste(img.crop((left, top, sw - right, sh - bottom)).resize((mid_w, mid_h), Image.LANCZOS), (left, top))
    return result


def _cocostudio_tree_text(obj, indent=0, lines=None) -> list:
    """Render a CocoStudio JSON layout as an indented widget tree."""
    if lines is None:
        lines = []

    tex_list = obj.get('texturesPng', obj.get('textureList', []))
    if tex_list:
        lines.append("Referenced Textures:")
        for t in tex_list[:20]:
            lines.append(f"    {t}")
        lines.append("")

    if isinstance(obj, dict) and 'armature_data' in obj:
        lines.append("Armature Data:")
        for arm in obj.get('armature_data', []):
            name = arm.get('name', '?')
            bones = len(arm.get('bone_data', []))
            lines.append(f"  Armature: {name} ({bones} bones)")
            for bone in arm.get('bone_data', [])[:20]:
                bname = bone.get('name', '?')
                lines.append(f"    Bone: {bname}")
        return lines

    root = _cs_get_root(obj)
    _cocostudio_node(root, indent, lines, is_last=True)
    return lines


def _cocostudio_node(obj, indent, lines, is_last=True, parent_lasts=None):
    """Render a single CocoStudio node and its children."""
    if parent_lasts is None:
        parent_lasts = []
    if not isinstance(obj, dict):
        return

    prefix = ""
    if indent > 0:
        for pl in parent_lasts:
            prefix += "   " if pl else "│  "
        prefix += "└─ " if is_last else "├─ "

    x, y, w, h, _ax, _ay, tex_path, cn, nm, *_ = _cs_widget_props(obj)

    parts = [f"[{cn}]"]
    if nm:
        parts.append(nm)
    if w > 0 and h > 0:
        parts.append(f"({w}x{h})")
    if x != 0 or y != 0:
        parts.append(f"@({x:.0f},{y:.0f})")
    if tex_path:
        parts.append(f"← {tex_path}")

    lines.append(f"{prefix}{' '.join(parts)}")

    children = obj.get('children', obj.get('gameobjects', []))
    if isinstance(children, list):
        child_lasts = parent_lasts + ([is_last] if indent > 0 else [])
        for i, child in enumerate(children):
            _cocostudio_node(child, indent + 1, lines,
                             is_last=(i == len(children) - 1),
                             parent_lasts=child_lasts)
        for comp in obj.get('components', []):
            if isinstance(comp, dict) and comp.get('fileData', {}).get('path'):
                fd = comp['fileData']
                cn = comp.get('classname', '?')
                prefix = "   " * indent + ("   " if is_last else "│  ") if indent > 0 else ""
                lines.append(f"{prefix}  → [{cn}] {fd['path']}")


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


# ---------------------------------------------------------------------------
# Background file loader
# ---------------------------------------------------------------------------
class FileLoaderWorker(QThread):
    """Loads a BGAD container in a background thread."""
    finished = pyqtSignal(object, list, str)  # (container, entries, path)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path

    def run(self):
        try:
            self.progress.emit(f"Parsing {os.path.basename(self._path)}...")
            container = KHUxBGADContainer(self._path)
            self.progress.emit("Decrypting entries...")
            entries = container.iter_entries()
            self.finished.emit(container, entries, self._path)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Audio player widget
# ---------------------------------------------------------------------------
class AudioPlayerWidget(QWidget):
    """Audio player with seekbar for OGG files extracted from AKB entries."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QSlider

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._info_label = QLabel("No audio loaded")
        self._info_label.setStyleSheet(f"color: {COLORS['fg']}; font: 10pt 'Consolas';")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._info_label)

        # Seekbar — click anywhere to jump
        class ClickSlider(QSlider):
            def mousePressEvent(self, event):
                if event.button() == Qt.MouseButton.LeftButton and self.maximum() > 0:
                    val = int(event.position().x() / self.width() * self.maximum())
                    self.setValue(val)
                    self.sliderMoved.emit(val)
                super().mousePressEvent(event)

        self._seekbar = ClickSlider(Qt.Orientation.Horizontal)
        self._seekbar.setRange(0, 0)
        self._seekbar.setEnabled(False)
        self._seekbar.sliderMoved.connect(self._seek)
        self._seekbar.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {COLORS['border']};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {COLORS['fg']};
                width: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }}
            QSlider::sub-page:horizontal {{
                background: {COLORS.get('accent', '#569cd6')};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self._seekbar)

        # Time label
        self._time_label = QLabel("0:00 / 0:00")
        self._time_label.setStyleSheet(f"color: {COLORS['fg_dim']}; font: 9pt 'Consolas';")
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._time_label)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._start_btn = QPushButton("<<")
        self._start_btn.setEnabled(False)
        self._start_btn.setFixedWidth(40)
        self._start_btn.clicked.connect(self._jump_start)
        btn_layout.addWidget(self._start_btn)

        self._play_btn = QPushButton("Play")
        self._play_btn.setEnabled(False)
        self._play_btn.setFixedWidth(80)
        self._play_btn.clicked.connect(self._toggle_play)
        btn_layout.addWidget(self._play_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.setFixedWidth(80)
        self._stop_btn.clicked.connect(self._stop)
        btn_layout.addWidget(self._stop_btn)

        self._end_btn = QPushButton(">>")
        self._end_btn.setEnabled(False)
        self._end_btn.setFixedWidth(40)
        self._end_btn.clicked.connect(self._jump_end)
        btn_layout.addWidget(self._end_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addStretch()

        self._player = None
        self._audio_output = None
        self._temp_file = None
        self._seeking = False

        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
            self._player = QMediaPlayer()
            self._audio_output = QAudioOutput()
            self._player.setAudioOutput(self._audio_output)
            self._player.positionChanged.connect(self._on_position_changed)
            self._player.durationChanged.connect(self._on_duration_changed)
            self._has_media = True
        except ImportError:
            self._has_media = False

    @staticmethod
    def _fmt_time(ms: int) -> str:
        s = ms // 1000
        return f"{s // 60}:{s % 60:02d}"

    def _on_position_changed(self, pos: int):
        if not self._seeking:
            self._seekbar.setValue(pos)
        dur = self._player.duration() if self._player else 0
        self._time_label.setText(f"{self._fmt_time(pos)} / {self._fmt_time(dur)}")

    def _on_duration_changed(self, dur: int):
        self._seekbar.setRange(0, dur)
        self._time_label.setText(f"0:00 / {self._fmt_time(dur)}")

    def _seek(self, pos: int):
        if self._player:
            self._seeking = True
            self._player.setPosition(pos)
            self._seeking = False

    def load_ogg(self, ogg_data: bytes, info_text: str = ""):
        self._stop()
        self._info_label.setText(info_text or "Audio loaded")

        if not self._has_media:
            self._info_label.setText("Audio playback unavailable\n(PyQt6.QtMultimedia not found)\n\nExport as .ogg to play externally")
            return

        import tempfile
        if self._temp_file:
            try:
                os.unlink(self._temp_file)
            except OSError:
                pass

        fd, path = tempfile.mkstemp(suffix=".ogg")
        os.write(fd, ogg_data)
        os.close(fd)
        self._temp_file = path

        from PyQt6.QtCore import QUrl
        self._player.setSource(QUrl.fromLocalFile(path))
        self._play_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._start_btn.setEnabled(True)
        self._end_btn.setEnabled(True)
        self._seekbar.setEnabled(True)

    def clear_audio(self):
        self._stop()
        self._info_label.setText("No audio loaded")
        self._play_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._start_btn.setEnabled(False)
        self._end_btn.setEnabled(False)
        self._seekbar.setEnabled(False)
        self._seekbar.setRange(0, 0)
        self._time_label.setText("0:00 / 0:00")

    def _toggle_play(self):
        if not self._player:
            return
        from PyQt6.QtMultimedia import QMediaPlayer
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self._play_btn.setText("Play")
        else:
            self._player.play()
            self._play_btn.setText("Pause")

    def _stop(self):
        if self._player:
            self._player.stop()
        self._play_btn.setText("Play")

    def _jump_start(self):
        if self._player:
            self._player.setPosition(0)

    def _jump_end(self):
        if self._player and self._player.duration() > 0:
            self._player.setPosition(self._player.duration())

    def cleanup(self):
        self._stop()
        if self._temp_file:
            try:
                os.unlink(self._temp_file)
            except OSError:
                pass
            self._temp_file = None


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

        # File label
        self._file_label = QLabel("No file loaded  (File > Open or Ctrl+O)")
        self._file_label.setStyleSheet(f"color: {COLORS['fg_dim']};")
        left_layout.addWidget(self._file_label)

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

        from PyQt6.QtWidgets import QCheckBox
        self._show_hidden_cb = QCheckBox("Show Hidden")
        self._show_hidden_cb.setChecked(False)
        self._show_hidden_cb.setStyleSheet(f"color: {COLORS['fg_dim']}; font-size: 9pt;")
        self._show_hidden_cb.toggled.connect(self._on_show_hidden_toggled)
        preview_toolbar.addWidget(self._show_hidden_cb)

        self._export_btn = QPushButton("Export")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export_entry)
        preview_toolbar.addWidget(self._export_btn)

        center_layout.addLayout(preview_toolbar)

        # Preview notebook
        self._preview_notebook = QTabWidget()

        # Preview tab (images + audio stacked)
        from PyQt6.QtWidgets import QStackedWidget
        self._preview_stack = QStackedWidget()
        self._image_preview = ImagePreviewWidget()
        self._image_preview.zoom_changed.connect(self._on_zoom_changed)
        self._audio_player = AudioPlayerWidget()
        self._preview_stack.addWidget(self._image_preview)   # index 0
        self._preview_stack.addWidget(self._audio_player)    # index 1
        self._preview_notebook.addTab(self._preview_stack, "Preview")

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

        quit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        quit_shortcut.activated.connect(self.close)

    def _on_show_hidden_toggled(self, checked: bool):
        if self.current_entry:
            self._show_preview(self.current_entry)

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
            "KHUx Files (*.mp4 *.png *.jpg *.gif *.lwf *.bin *.ExportJson *.json);;All Files (*.*)",
        )
        if path:
            self._load_file(path)

    def _load_file(self, path: str):
        if not os.path.exists(path):
            QMessageBox.critical(self, "Error", f"File not found:\n{path}")
            return

        self._status_left.setText(f"Loading {os.path.basename(path)}...")

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
            pass

        self._loader = FileLoaderWorker(path)
        self._loader.progress.connect(self._status_left.setText)
        self._loader.error.connect(self._on_load_error)
        self._loader.finished.connect(self._on_load_finished)
        self._loader.start()

    def _on_load_error(self, msg: str):
        QMessageBox.critical(self, "Error", f"Failed to parse container:\n{msg}")
        self._status_left.setText("Ready")
        self._loader = None

    def _on_load_finished(self, _container, entries: list, path: str):
        self._loader = None
        self.current_file = path
        self.entries = entries

        self._resolve_names_via_bgi(path)

        self.entry_map = {e.name: e for e in entries}
        self._basename_map: Dict[str, BGADEntry] = {}
        for e in entries:
            base = e.name.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
            if base not in self._basename_map:
                self._basename_map[base] = e

        self.entry_formats = {}
        self.entry_link_targets: Dict[str, int] = {}
        entry_list = list(entries)
        # Build real-only table: non-stub entries.
        # 4-byte .txt with printable ASCII are real data, not stubs.
        def _is_stub(e):
            if len(e.data) != 4:
                return False
            if e.name.lower().endswith(".txt"):
                try:
                    text = e.data.decode("utf-8")
                    if all(32 <= ord(c) < 127 or c in "\n\r\t" for c in text):
                        return False
                except (UnicodeDecodeError, ValueError):
                    pass
            return True
        real_table = [i for i, e in enumerate(entry_list) if not _is_stub(e)]
        for e in entry_list:
            if e.name.lower().endswith(".ttf"):
                self.entry_formats[e.name] = "ttf"
            elif e.data and len(e.data) >= 4:
                fmt = detect_format(e.data[:4])
                if fmt == "index" and _is_stub(e):
                    import struct as _struct
                    stub_val = _struct.unpack("<I", e.data[:4])[0]
                    if stub_val < len(real_table):
                        target_idx = real_table[stub_val]
                        target_data = entry_list[target_idx].data
                        real_fmt = detect_format(target_data[:4])
                        self.entry_formats[e.name] = f"link:{real_fmt}"
                        self.entry_link_targets[e.name] = target_idx
                    else:
                        self.entry_formats[e.name] = "index"
                else:
                    if fmt in ("json", "text") and len(e.data) > 20:
                        try:
                            probe = json.loads(e.data.decode("utf-8", errors="replace"))
                            if _detect_cocostudio(probe):
                                fmt = "ui"
                        except (json.JSONDecodeError, ValueError):
                            pass
                    self.entry_formats[e.name] = fmt
            else:
                self.entry_formats[e.name] = "unknown"

        norm_path = os.path.normpath(path)
        if norm_path in self.recent_files:
            self.recent_files.remove(norm_path)
        self.recent_files.insert(0, norm_path)
        self.recent_files = self.recent_files[:10]
        self._save_recent_files()
        self._rebuild_recent_menu()

        fname = os.path.basename(path)
        self._file_label.setText(fname)
        self._file_label.setStyleSheet(f"color: {COLORS['fg_bright']};")

        self._populate_tree()

        self._status_left.setText(f"Loaded {fname}")
        self._status_right.setText(f"{len(entries)} entries")

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
            if fmt.startswith("link:"):
                real_fmt = fmt[5:]
                real_badge = FORMAT_BADGES.get(real_fmt, real_fmt.upper())
                badge = f"[LINK | {real_badge.strip('[]')}]"
                fmt = real_fmt
            else:
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

        # For link entries, show properties of the stub but preview the target
        fmt = self.entry_formats.get(entry_name, "")
        preview_entry = entry
        if fmt.startswith("link:") and entry_name in self.entry_link_targets:
            target_idx = self.entry_link_targets[entry_name]
            entry_list = list(self.entries) if not isinstance(self.entries, list) else self.entries
            if target_idx < len(entry_list):
                preview_entry = entry_list[target_idx]

        self._show_entry_properties(entry)
        self._show_hex_view(entry)
        self._show_preview(preview_entry)

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
        display_fmt = fmt
        if fmt.startswith("link:"):
            real_fmt = fmt[5:]
            display_fmt = f"LINK -> {real_fmt.upper()}"
            if entry.name in self.entry_link_targets:
                target_idx = self.entry_link_targets[entry.name]
                import struct as _struct
                stub_val = _struct.unpack("<I", entry.data[:4])[0]
                entry_list = list(self.entries) if not isinstance(self.entries, list) else self.entries
                target_name = entry_list[target_idx].name if target_idx < len(entry_list) else "?"
                self._props_text.append_kv("Format", display_fmt)
                self._props_text.append_kv("Stub Value", str(stub_val))
                self._props_text.append_kv("Resolves To", f"[{target_idx}] {target_name}")
            else:
                self._props_text.append_kv("Format", display_fmt)
        else:
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
        elif fmt == "akb":
            self._show_akb_properties(entry)
        elif fmt in ("plist", "json"):
            self._show_text_properties(entry)
        elif fmt == "lwf":
            self._show_lwf_properties(entry)

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

    def _show_akb_properties(self, entry: BGADEntry):
        try:
            from khux.formats.akb import parse_akb
            akb = parse_akb(entry.data)
            self._props_text.append_header("\nAKB Audio")
            self._props_text.append_separator()
            self._props_text.append_kv("Version", str(akb.version))
            self._props_text.append_kv("Header Size", f"{akb.header_size} bytes")
            self._props_text.append_kv("OGG Offset", str(akb.ogg_offset))
            self._props_text.append_kv("OGG Size", _format_size(len(akb.ogg_data)))
            if akb.sample_rate:
                self._props_text.append_kv("Sample Rate", f"{akb.sample_rate} Hz")
            if akb.channels:
                self._props_text.append_kv("Channels", str(akb.channels))
            self._props_text.append_dim("\nExport as .ogg to play in any audio player")
        except Exception as e:
            self._props_text.append_dim(f"\n[AKB parse error: {e}]")

    def _show_text_properties(self, entry: BGADEntry):
        try:
            text = entry.data.decode("utf-8", errors="replace")
            lines = text.count("\n") + 1
            self._props_text.append_header("\nText Info")
            self._props_text.append_separator()
            self._props_text.append_kv("Lines", str(lines))
            self._props_text.append_kv("Characters", str(len(text)))

            stripped = text.lstrip()
            if stripped.startswith(("{", "[")):
                try:
                    obj = json.loads(text)
                    if _detect_cocostudio(obj):
                        self._props_text.append_header("\nCocoStudio Layout")
                        self._props_text.append_separator()
                        classname = "?"
                        node = obj
                        if 'nodeTree' in node:
                            node = node['nodeTree']
                        if 'Content' in node and 'classname' not in node:
                            node = node['Content']
                            if isinstance(node, dict) and 'Content' in node:
                                node = node['Content']
                        if isinstance(node, dict):
                            classname = node.get('classname', '?')
                        self._props_text.append_kv("Root Class", classname)
                        child_count = self._count_cocostudio_nodes(obj)
                        self._props_text.append_kv("Total Widgets", str(child_count))
                        if 'textureList' in obj:
                            self._props_text.append_kv("Textures", str(len(obj['textureList'])))
                        if 'armature_data' in obj:
                            self._props_text.append_kv("Armatures", str(len(obj['armature_data'])))
                except (json.JSONDecodeError, ValueError):
                    pass
        except Exception:
            pass

    @staticmethod
    def _count_cocostudio_nodes(obj) -> int:
        if not isinstance(obj, dict):
            return 0
        count = 1 if 'classname' in obj else 0
        for key in ('children', 'nodeTree', 'Content', 'widgetTree'):
            val = obj.get(key)
            if isinstance(val, list):
                for child in val:
                    count += KHUxExplorer._count_cocostudio_nodes(child)
            elif isinstance(val, dict):
                count += KHUxExplorer._count_cocostudio_nodes(val)
        return count

    def _show_lwf_properties(self, entry: BGADEntry):
        try:
            info = _parse_lwf_data(entry.data)
            self._props_text.append_header("\nLWF Animation")
            self._props_text.append_separator()
            self._props_text.append_kv("Version", info.get('version_str', '?'))
            self._props_text.append_kv("Data Size", _format_size(info.get('data_size', 0)))
            self._props_text.append_kv("Total Size", _format_size(info.get('total_size', 0)))
            if 'string_byte_length' in info:
                self._props_text.append_kv("String Data", _format_size(info['string_byte_length']))
            if 'animation_byte_length' in info:
                self._props_text.append_kv("Animation Data", _format_size(info['animation_byte_length']))

            counts = info.get('counts', {})
            active = {k: v for k, v in counts.items() if v > 0}
            if active:
                self._props_text.append_header("\nData Sections")
                self._props_text.append_separator()
                for name, val in active.items():
                    self._props_text.append_kv(name, str(val))

            textures = info.get('textures', [])
            if textures:
                self._props_text.append_header(f"\nTextures ({len(textures)})")
                self._props_text.append_separator()
                for t in textures:
                    self._props_text.append_dim(f"  {t}")
        except Exception as e:
            self._props_text.append_dim(f"\n[LWF parse error: {e}]")

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

        # Generic master data decryption — try schema-based parser first
        try:
            import struct as _struct
            seed, psize, decrypted = decrypt_master_data_payload(entry.data)

            table_type = self._get_master_table_type()
            detected = None
            if HAS_MASTER_PARSER and self.current_file:
                detected = _master_parser.detect_table(self.current_file)
            display_type = detected or table_type or "unknown"
            has_schema = HAS_MASTER_PARSER and display_type in _master_parser.schemas

            self._props_text.append_header(f"\nDecrypted: {display_type}" + (" [schema]" if has_schema else ""))
            self._props_text.append_separator()

            if has_schema:
                record = _master_parser.parse_entry_bytes(entry.data, display_type)
                for k, v in record.items():
                    if k.startswith("_"):
                        continue
                    self._props_text.append_kv(k, str(v))
            else:
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

            self._props_text.append_kv("Table", display_type)
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

        self._audio_player.clear_audio()
        self._preview_stack.setCurrentIndex(0)  # Default to image view

        # Always populate hex dump tab so it's available for any entry
        self._show_hex_preview(entry)

        if fmt == "btf" and HAS_BTF and HAS_PIL:
            self._show_btf_preview(entry)
            self._preview_stack.setCurrentIndex(0)  # Image
            self._preview_notebook.setCurrentIndex(0)  # Preview tab
            self._zoom_in_btn.setEnabled(True)
            self._zoom_out_btn.setEnabled(True)
        elif fmt == "ttf" and HAS_PIL:
            self._show_ttf_preview(entry)
            self._preview_stack.setCurrentIndex(0)  # Image
            self._preview_notebook.setCurrentIndex(0)  # Preview tab
            self._zoom_in_btn.setEnabled(True)
            self._zoom_out_btn.setEnabled(True)
        elif fmt == "akb":
            self._show_akb_audio(entry)
            self._preview_stack.setCurrentIndex(1)  # Audio
            self._preview_notebook.setCurrentIndex(0)  # Preview tab
            self._zoom_in_btn.setEnabled(False)
            self._zoom_out_btn.setEnabled(False)
        elif fmt == "lwf":
            self._show_lwf_preview(entry)
            self._render_lwf_visual(entry)
            self._preview_stack.setCurrentIndex(0)
            self._preview_notebook.setCurrentIndex(0)
            self._zoom_in_btn.setEnabled(True)
            self._zoom_out_btn.setEnabled(True)
        elif fmt == "ui":
            self._show_text_preview(entry)
            self._render_cocostudio_visual(entry)
            self._preview_stack.setCurrentIndex(0)
            self._preview_notebook.setCurrentIndex(0)
            self._zoom_in_btn.setEnabled(True)
            self._zoom_out_btn.setEnabled(True)
        elif fmt in ("plist", "json") or self._is_text_data(entry.data):
            self._show_text_preview(entry)
            if self._render_cocostudio_visual(entry):
                self._preview_stack.setCurrentIndex(0)
                self._preview_notebook.setCurrentIndex(0)
                self._zoom_in_btn.setEnabled(True)
                self._zoom_out_btn.setEnabled(True)
            else:
                self._preview_notebook.setCurrentIndex(1)
                self._zoom_in_btn.setEnabled(False)
                self._zoom_out_btn.setEnabled(False)
        elif HAS_MASTER_DATA and self._is_master_data_container() and entry.name.isdigit() and len(entry.data) >= 8:
            self._show_master_data_preview(entry)
            self._zoom_in_btn.setEnabled(False)
            self._zoom_out_btn.setEnabled(False)
        else:
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

    def _find_entry(self, path: str) -> Optional[BGADEntry]:
        """Find a BGAD entry by full path, basename, prefix variations, or decoded hex name."""
        e = self.entry_map.get(path)
        if e:
            return e
        for prefix in ('cocostudio/', 'cocostudio/publish/'):
            e = self.entry_map.get(prefix + path)
            if e:
                return e
        base = path.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
        e = getattr(self, '_basename_map', {}).get(base)
        if e:
            return e
        return None

    def _render_lwf_visual(self, entry: BGADEntry) -> bool:
        """Render LWF referenced textures as a visual grid in the Preview tab."""
        if not HAS_PIL:
            return False
        info = _parse_lwf_data(entry.data)
        tex_names = info.get('textures', [])
        resolved = info.get('texture_resolved', {})

        images = []
        if HAS_BTF:
            for tn in tex_names:
                decoded = resolved.get(tn, tn)
                e = self._find_entry(tn) or self._find_entry(decoded)
                if e and len(e.data) >= 4 and e.data[:4] == b'\x89BTF':
                    try:
                        images.append((decoded.rsplit('/', 1)[-1], KHUxBTF.from_bytes(e.data).decode(use_canvas=True)))
                    except Exception:
                        pass

        if not images:
            canvas = Image.new('RGBA', (500, 300), (30, 30, 30, 255))
            draw = ImageDraw.Draw(canvas)
            y = 20
            draw.text((20, y), f"LWF v{info.get('version_str', '?')}", fill=(200, 200, 200))
            y += 25
            active = {k: v for k, v in info.get('counts', {}).items() if 0 < v < 100000}
            if active:
                draw.text((20, y), f"{active.get('texture', 0)} textures, {active.get('frame', 0)} frames, {active.get('movie', 0)} movies", fill=(150, 150, 150))
                y += 25
            if tex_names:
                draw.text((20, y), "Referenced textures:", fill=(140, 180, 220))
                y += 20
                for tn in tex_names[:8]:
                    decoded = resolved.get(tn, tn)
                    draw.text((30, y), decoded, fill=(120, 160, 200))
                    y += 18
                if not self.entry_map or len(self.entry_map) <= 1:
                    y += 10
                    draw.text((20, y), "Textures not found (open inside BGAD container)", fill=(200, 150, 80))
            else:
                draw.text((20, y), "No texture references found in string table", fill=(200, 150, 80))
            self._current_pil_image = canvas
            self._image_preview.set_pixmap(_pil_image_to_qpixmap(canvas))
            return True

        padding, max_thumb, label_h = 8, 256, 18
        thumbs = []
        for name, img in images:
            s = min(max_thumb / max(img.width, 1), max_thumb / max(img.height, 1), 1.0)
            if s < 1.0:
                img = img.resize((int(img.width * s), int(img.height * s)), Image.LANCZOS)
            thumbs.append((name, img))

        cols = min(4, len(thumbs))
        cell_w = max(t.width for _, t in thumbs) + padding * 2
        cell_h = max(t.height for _, t in thumbs) + padding * 2 + label_h
        rows = (len(thumbs) + cols - 1) // cols
        title_h = 28

        canvas = Image.new('RGBA', (cols * cell_w + padding, rows * cell_h + padding + title_h), (30, 30, 30, 255))
        draw = ImageDraw.Draw(canvas)
        draw.text((padding, 6), f"LWF Textures ({len(thumbs)})", fill=(200, 200, 200))

        for i, (name, img) in enumerate(thumbs):
            cx = (i % cols) * cell_w + padding
            cy = (i // cols) * cell_h + padding + title_h
            draw.rectangle([cx, cy, cx + cell_w - 1, cy + cell_h - 1], fill=(45, 45, 48), outline=(80, 80, 80))
            canvas.alpha_composite(img, (cx + (cell_w - img.width) // 2, cy + padding))
            draw.text((cx + 4, cy + cell_h - label_h), name[:30], fill=(170, 170, 170))

        self._current_pil_image = canvas
        self._image_preview.set_pixmap(_pil_image_to_qpixmap(canvas))
        return True

    def _render_cocostudio_visual(self, entry: BGADEntry) -> bool:
        """Render a CocoStudio layout as a visual preview with textures or wireframe."""
        if not HAS_PIL:
            return False
        try:
            obj = json.loads(entry.data.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            return False
        if not _detect_cocostudio(obj):
            return False

        if 'gameobjects' in obj and 'widgetTree' not in obj:
            return self._render_scene_composite(obj)

        root = _cs_get_root(obj)
        if not isinstance(root, dict):
            return False

        show_hidden = getattr(self, '_show_hidden_cb', None) and self._show_hidden_cb.isChecked()
        bx1, by1, bx2, by2 = _cs_bounding_box(root, show_hidden=show_hidden)
        pad = 1
        w = max(int(bx2 - bx1) + pad * 2, 50)
        h = max(int(by2 - by1) + pad * 2, 50)
        off_x = (-bx1 if bx1 < 0 else 0) + pad
        off_y = (-by1 if by1 < 0 else 0) + pad

        canvas = Image.new('RGBA', (w, h), (40, 40, 42, 255))
        has_tex = self._cs_render_node(canvas, root, off_x, off_y, show_hidden)

        if not has_tex:
            draw = ImageDraw.Draw(canvas)
            self._cs_wireframe(draw, canvas.height, root, 0, 0)

        self._current_pil_image = canvas
        self._image_preview.set_pixmap(_pil_image_to_qpixmap(canvas))
        return True

    def _render_scene_composite(self, obj) -> bool:
        """Render a Scene file by compositing referenced sub-layouts at their positions."""
        canvas = Image.new('RGBA', (960, 640), (40, 40, 42, 255))
        rendered_any = False
        show_hidden = getattr(self, '_show_hidden_cb', None) and self._show_hidden_cb.isChecked()

        def process_gameobjects(gos, parent_x, parent_y):
            nonlocal rendered_any
            for go in gos:
                if not show_hidden and not go.get('visible', 1):
                    continue
                gx = parent_x + float(go.get('x', 0))
                gy = parent_y + float(go.get('y', 0))
                for comp in go.get('components', []):
                    if comp.get('classname') != 'GUIComponent':
                        continue
                    fd = comp.get('fileData', {})
                    if not fd.get('path'):
                        continue
                    sub_entry = self._find_entry(fd['path'])
                    if not sub_entry:
                        continue
                    try:
                        sub_obj = json.loads(sub_entry.data.decode('utf-8'))
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if 'widgetTree' not in sub_obj:
                        continue
                    root = sub_obj['widgetTree']
                    bx1, by1, bx2, by2 = _cs_bounding_box(root, show_hidden=show_hidden)
                    sw = max(int(bx2 - bx1), 50)
                    sh = max(int(by2 - by1), 50)
                    sub_canvas = Image.new('RGBA', (sw, sh), (0, 0, 0, 0))
                    ox = -bx1 if bx1 < 0 else 0
                    oy = -by1 if by1 < 0 else 0
                    self._cs_render_node(sub_canvas, root, ox, oy, show_hidden)
                    dx = int(gx)
                    dy = int(640 - gy - sub_canvas.height)
                    sx, sy = 0, 0
                    if dx < 0:
                        sx = -dx; dx = 0
                    if dy < 0:
                        sy = -dy; dy = 0
                    cw = min(sub_canvas.width - sx, canvas.width - dx)
                    ch = min(sub_canvas.height - sy, canvas.height - dy)
                    if cw > 0 and ch > 0:
                        canvas.alpha_composite(sub_canvas.crop((sx, sy, sx + cw, sy + ch)), (dx, dy))
                        rendered_any = True
                process_gameobjects(go.get('gameobjects', []), gx, gy)

        process_gameobjects(obj.get('gameobjects', []), 0, 0)

        if not rendered_any:
            draw = ImageDraw.Draw(canvas)
            draw.text((20, 20), "Scene (no renderable GUIComponents)", fill=(150, 150, 150))

        self._current_pil_image = canvas
        self._image_preview.set_pixmap(_pil_image_to_qpixmap(canvas))
        return True

    def _cs_render_node(self, canvas, node, px, py, show_hidden=False) -> bool:
        """Recursively render CocoStudio widgets. px/py = parent's anchor point in world coords."""
        if not isinstance(node, dict) or not HAS_BTF:
            return False
        opts_vis = node.get('options', node)
        if not show_hidden and not opts_vis.get('visible', True):
            return False
        x, y, w, h, ax, ay, tex_path, cn, nm, s9, s9x, s9y, s9w, s9h = _cs_widget_props(node)

        anchor_wx = px + x
        anchor_wy = py + y
        bl_x = anchor_wx - w * ax
        bl_y = anchor_wy - h * ay
        pil_x = int(bl_x)
        pil_y = int(canvas.height - bl_y - h)

        rendered = False
        if tex_path:
            e = self._find_entry(tex_path)
            if e and len(e.data) >= 4 and e.data[:4] == b'\x89BTF':
                try:
                    img = KHUxBTF.from_bytes(e.data).decode(use_canvas=True)
                    if w > 0 and h > 0 and (w, h) != img.size:
                        if s9:
                            img = _scale9_resize(img, w, h, s9x, s9y, s9w, s9h)
                        else:
                            img = img.resize((w, h), Image.LANCZOS)
                    src_x, src_y = 0, 0
                    dx, dy = pil_x, pil_y
                    if dx < 0:
                        src_x = -dx; dx = 0
                    if dy < 0:
                        src_y = -dy; dy = 0
                    cw = min(img.width - src_x, canvas.width - dx)
                    ch = min(img.height - src_y, canvas.height - dy)
                    if cw > 0 and ch > 0:
                        cropped = img.crop((src_x, src_y, src_x + cw, src_y + ch))
                        canvas.alpha_composite(cropped, (dx, dy))
                        rendered = True
                except Exception:
                    pass

        if cn == "Label" and w > 0 and h > 0:
            opts = node.get("options", node)
            text = opts.get("text", "")
            if text:
                font_size = int(opts.get("fontSize", 14))
                cr = int(opts.get("colorR", 255))
                cg = int(opts.get("colorG", 255))
                cb = int(opts.get("colorB", 255))
                halign = int(opts.get("hAlignment", 0))
                valign = int(opts.get("vAlignment", 0))
                font = self._get_cs_font(opts.get("fontName", ""), font_size)
                draw = ImageDraw.Draw(canvas)
                bbox = draw.textbbox((0, 0), text, font=font) if font else (0, 0, len(text) * 8, font_size)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                tx = pil_x
                ty = pil_y
                if halign == 1:
                    tx = pil_x + (w - tw) // 2
                elif halign == 2:
                    tx = pil_x + w - tw
                if valign == 1:
                    ty = pil_y + (h - th) // 2
                elif valign == 2:
                    ty = pil_y + h - th
                tx = max(0, tx)
                ty = max(0, ty)
                if 0 <= tx < canvas.width and 0 <= ty < canvas.height:
                    draw.text((tx, ty), text, fill=(cr, cg, cb), font=font)
                rendered = True

        if not rendered and w > 10 and h > 10:
            draw = ImageDraw.Draw(canvas)
            rx = max(0, pil_x)
            ry = max(0, pil_y)
            rw = min(w, canvas.width - rx)
            rh = min(h, canvas.height - ry)
            if rw > 0 and rh > 0:
                draw.rectangle([rx, ry, rx + rw, ry + rh], outline=(90, 140, 200))
                label = f"{cn}: {nm}"[:35] if nm else str(cn)
                draw.text((rx + 3, ry + 2), label, fill=(140, 180, 220))

        for child in node.get('children', []):
            if self._cs_render_node(canvas, child, anchor_wx, anchor_wy, show_hidden):
                rendered = True
        return rendered

    _cs_font_cache: Dict[tuple, Any] = {}

    def _get_cs_font(self, font_name: str, size: int):
        key = (font_name, size)
        if key not in self._cs_font_cache:
            import tempfile
            e = self._find_entry(font_name)
            if e and len(e.data) > 100:
                fd, path = tempfile.mkstemp(suffix=".ttf")
                os.write(fd, e.data)
                os.close(fd)
                try:
                    self._cs_font_cache[key] = ImageFont.truetype(path, size)
                except Exception:
                    self._cs_font_cache[key] = None
                finally:
                    os.unlink(path)
            else:
                self._cs_font_cache[key] = None
        return self._cs_font_cache[key]

    def _cs_wireframe(self, draw, canvas_h, node, px, py):
        """Draw wireframe boxes. px/py = parent's anchor point in world coords."""
        if not isinstance(node, dict):
            return
        x, y, w, h, ax, ay, _tp, cn, nm, *_ = _cs_widget_props(node)

        anchor_wx = px + x
        anchor_wy = py + y
        bl_x = anchor_wx - w * ax
        bl_y = anchor_wy - h * ay
        pil_x = max(0, int(bl_x))
        pil_y = max(0, int(canvas_h - bl_y - h))

        if w > 10 and h > 10:
            rw = min(w, int(draw.im.size[0]) - pil_x)
            rh = min(h, int(draw.im.size[1]) - pil_y)
            if rw > 0 and rh > 0:
                draw.rectangle([pil_x, pil_y, pil_x + rw, pil_y + rh], outline=(90, 140, 200))
                label = f"{cn}: {nm}"[:35] if nm else str(cn)
                draw.text((pil_x + 3, pil_y + 2), label, fill=(140, 180, 220))

        for child in node.get('children', []):
            self._cs_wireframe(draw, canvas_h, child, anchor_wx, anchor_wy)

    def _show_lwf_preview(self, entry: BGADEntry):
        """Show LWF structure as formatted text in the text preview tab."""
        try:
            info = _parse_lwf_data(entry.data)
            lines = []
            lines.append(f"{'═' * 50}")
            lines.append(f"  LWF Animation — v{info.get('version_str', '?')}")
            lines.append(f"{'═' * 50}")
            lines.append("")
            lines.append(f"  Data Size:       {_format_size(info.get('data_size', 0))}")
            lines.append(f"  Total Size:      {_format_size(info.get('total_size', 0))}")
            if 'string_byte_length' in info:
                lines.append(f"  String Data:     {_format_size(info['string_byte_length'])}")
            if 'animation_byte_length' in info:
                lines.append(f"  Animation Data:  {_format_size(info['animation_byte_length'])}")

            counts = info.get('counts', {})
            active = {k: v for k, v in counts.items() if v > 0}
            if active:
                lines.append("")
                lines.append(f"{'─' * 50}")
                lines.append("  Data Sections")
                lines.append(f"{'─' * 50}")
                for name, val in active.items():
                    lines.append(f"    {name:<24} {val:>6}")

            textures = info.get('textures', [])
            if textures:
                lines.append("")
                lines.append(f"{'─' * 50}")
                lines.append(f"  Textures ({len(textures)})")
                lines.append(f"{'─' * 50}")
                for t in textures:
                    lines.append(f"    {t}")

            strings = info.get('strings', [])
            if strings:
                lines.append("")
                lines.append(f"{'─' * 50}")
                lines.append(f"  String Table ({len(strings)} entries)")
                lines.append(f"{'─' * 50}")
                texture_set = set(textures)
                for i, s in enumerate(strings[:300]):
                    marker = "  [TEX]" if s in texture_set else ""
                    lines.append(f"    [{i:4d}] {s}{marker}")
                if len(strings) > 300:
                    lines.append(f"    ... and {len(strings) - 300} more")

            self._preview_text.setPlainText("\n".join(lines))
        except Exception as e:
            self._preview_text.setPlainText(f"LWF parse error: {e}")

    def _show_ttf_preview(self, entry: BGADEntry):
        """Render a TTF font preview: sample header + glyph grid."""
        import tempfile
        try:
            # Write font bytes to a temp file so PIL can load it
            with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as tmp:
                tmp.write(entry.data)
                tmp_path = tmp.name

            try:
                header_font = ImageFont.truetype(tmp_path, 32)
                grid_font = ImageFont.truetype(tmp_path, 20)
            finally:
                os.unlink(tmp_path)

            bg_color = (30, 30, 30)
            fg_color = (204, 204, 204)
            box_fg = (224, 224, 224)
            box_bg = (45, 45, 48)
            box_border = (80, 80, 80)
            padding = 20

            # --- Header ---
            sample_text = "AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRrSsTtUuVvWwXxYyZz 0123456789 !@#$%^&*()"
            # Measure header text
            tmp_img = Image.new("RGB", (1, 1))
            tmp_draw = ImageDraw.Draw(tmp_img)
            header_bbox = tmp_draw.textbbox((0, 0), sample_text, font=header_font)
            header_w = header_bbox[2] - header_bbox[0] + padding * 2
            header_h = header_bbox[3] - header_bbox[1] + padding

            # --- Glyph grid ---
            # Characters 32-126 (printable ASCII)
            glyphs = [chr(c) for c in range(32, 127)]
            cell_size = 36
            cols = max(1, (max(header_w, 800) - padding * 2) // cell_size)
            rows = (len(glyphs) + cols - 1) // cols

            grid_w = cols * cell_size
            grid_h = rows * cell_size

            # Final image dimensions
            img_w = max(header_w, grid_w + padding * 2)
            img_h = padding + header_h + padding + grid_h + padding

            img = Image.new("RGB", (img_w, img_h), bg_color)
            draw = ImageDraw.Draw(img)

            # Draw header text
            draw.text((padding, padding), sample_text, fill=fg_color, font=header_font)

            # Draw glyph grid
            grid_top = padding + header_h + padding
            grid_left = padding
            for idx, ch in enumerate(glyphs):
                col = idx % cols
                row = idx // cols
                x = grid_left + col * cell_size
                y = grid_top + row * cell_size

                # Box background and border
                draw.rectangle([x, y, x + cell_size - 1, y + cell_size - 1],
                               fill=box_bg, outline=box_border)

                # Center the glyph in the cell
                ch_bbox = draw.textbbox((0, 0), ch, font=grid_font)
                ch_w = ch_bbox[2] - ch_bbox[0]
                ch_h = ch_bbox[3] - ch_bbox[1]
                cx = x + (cell_size - ch_w) // 2 - ch_bbox[0]
                cy = y + (cell_size - ch_h) // 2 - ch_bbox[1]
                draw.text((cx, cy), ch, fill=box_fg, font=grid_font)

            self._current_pil_image = img
            pixmap = _pil_image_to_qpixmap(img)
            self._image_preview.set_pixmap(pixmap)

        except Exception as e:
            self._image_preview.show_error(f"TTF preview error: {e}")

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
                    if _detect_cocostudio(obj):
                        tree_lines = _cocostudio_tree_text(obj)
                        tree_text = "\n".join(tree_lines)
                        truncated = self._truncate_json(obj, depth=0, max_depth=4)
                        pretty = json.dumps(truncated, indent=2, ensure_ascii=False)
                        combined = (
                            f"{'═' * 50}\n"
                            f"  CocoStudio Layout\n"
                            f"{'═' * 50}\n\n"
                            f"{tree_text}\n\n"
                            f"{'═' * 50}\n"
                            f"  JSON Data\n"
                            f"{'═' * 50}\n\n"
                            f"{pretty}"
                        )
                        self._preview_text.setPlainText(combined)
                        return
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

            # Pretty-print XML/plist
            if fmt == "plist" or stripped.startswith("<?xml") or stripped.startswith("<plist"):
                try:
                    import xml.dom.minidom
                    dom = xml.dom.minidom.parseString(entry.data)
                    pretty_xml = dom.toprettyxml(indent="  ")
                    lines = pretty_xml.split("\n")
                    if lines and lines[0].startswith("<?xml"):
                        lines = lines[1:]
                    self._preview_text.setPlainText("\n".join(lines))
                    return
                except Exception:
                    pass

            self._preview_text.setPlainText(text)
        except Exception as e:
            self._preview_text.setPlainText(f"Decode error: {e}")

    def _show_akb_audio(self, entry: BGADEntry):
        """Load AKB audio into the audio player widget."""
        try:
            from khux.formats.akb import parse_akb
            akb = parse_akb(entry.data)

            info = f"AKB Audio — {_format_size(len(akb.ogg_data))} OGG"
            if akb.sample_rate:
                info += f" — {akb.sample_rate} Hz"
            if akb.channels:
                info += f" — {akb.channels}ch"

            self._audio_player.load_ogg(akb.ogg_data, info)
        except Exception as e:
            self._audio_player.clear_audio()
            self._preview_text.setPlainText(f"AKB parse error: {e}")
            self._preview_notebook.setCurrentIndex(1)

    def _show_hex_preview(self, entry: BGADEntry):
        self._preview_hex.setPlainText(_hex_dump(entry.data, length=4096))

    def _show_master_data_preview(self, entry: BGADEntry):
        """Decrypt master data and show as JSON (if schema exists) or hex dump."""
        try:
            seed, psize, decrypted = decrypt_master_data_payload(entry.data)

            # Always update hex tab with decrypted bytes
            self._preview_hex.setPlainText(
                f"Decrypted (seed=0x{seed:08x}, size={psize}):\n\n"
                + _hex_dump(decrypted, length=4096)
            )

            # Try struct→JSON via MasterDataParser
            if HAS_MASTER_PARSER:
                table_name = self._get_master_table_type()
                if not table_name and self.current_file:
                    table_name = _master_parser.detect_table(self.current_file)
                record = _master_parser.parse_entry_bytes(entry.data, table_name or "")
                if "_raw_hex" not in record:
                    pretty = json.dumps(record, indent=2, ensure_ascii=False)
                    html = self._json_to_html(pretty)
                    self._preview_text.setHtml(
                        f'<pre style="font-family:Consolas;font-size:10pt;color:{COLORS["fg"]};'
                        f'background-color:{COLORS["text_bg"]};margin:0;white-space:pre-wrap;">'
                        f'{html}</pre>'
                    )
                    self._preview_notebook.setCurrentIndex(1)
                    return

            # Fallback: try UTF-8 text / JSON
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
                self._preview_notebook.setCurrentIndex(1)
            except UnicodeDecodeError:
                self._preview_hex.setPlainText(
                    f"Decrypted master data (seed=0x{seed:08x}, size={psize}):\n\n"
                    + _hex_dump(decrypted, length=4096)
                )
                self._preview_notebook.setCurrentIndex(2)
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
        elif fmt == "akb":
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Audio",
                os.path.splitext(default_name)[0] + ".ogg",
                "OGG Audio (*.ogg);;Raw AKB (*.*)",
            )
            if path:
                if path.lower().endswith(".ogg"):
                    try:
                        from khux.formats.akb import parse_akb
                        akb = parse_akb(entry.data)
                        self._write_raw(path, akb.ogg_data)
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
        self._basename_map = {entry.name: entry}
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
        self._basename_map = {entry.name: entry}
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
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)
    app.setStyle("Fusion")

    window = KHUxExplorer()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
