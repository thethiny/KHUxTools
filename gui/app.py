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
    from PIL import Image, ImageChops, ImageDraw, ImageFont
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
    "anim":    "#e6c07b",
    "scene":   "#98c379",
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
    "anim":    "[ANIM]",
    "scene":   "[SCENE]",
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


_LWF_ITEM_ARRAYS = [
    "stringBytes", "animationBytes", "translate", "matrix", "color",
    "alphaTransform", "colorTransform", "objectData", "texture",
    "textureFragment", "bitmap", "bitmapEx", "font", "textProperty",
    "text", "particleData", "particle", "programObject", "graphicObject",
    "graphic", "animation", "buttonCondition", "button", "label",
    "instanceName", "eventData", "place", "controlMoveM", "controlMoveC",
    "controlMoveMC", "control", "frame", "movieClipEvent", "movie",
    "movieLinkage", "stringData",
]

_LWF_CT_MOVE_M, _LWF_CT_MOVE_C, _LWF_CT_MOVE_MC = 2, 3, 4
_LWF_OT_GRAPHIC, _LWF_OT_MOVIE, _LWF_OT_BITMAP = 1, 2, 3


def _parse_lwf_data(data: bytes) -> dict:
    """Parse LWF binary using the GREE spec. Returns full parsed structure."""
    import struct as _st
    info = {'strings': [], 'textures': [], 'texture_resolved': {}, 'counts': {}}
    if len(data) < 324 or data[:4] != b"LWF\x00":
        return info

    info['version'] = data[4]
    info['version_str'] = f"{data[4]}.{data[5]}.{data[6]}"
    info['width'] = _st.unpack_from('<i', data, 8)[0]
    info['height'] = _st.unpack_from('<i', data, 12)[0]
    info['frameRate'] = _st.unpack_from('<i', data, 16)[0]
    info['rootMovieId'] = _st.unpack_from('<i', data, 20)[0]
    info['nameStringId'] = _st.unpack_from('<i', data, 24)[0]

    items = {}
    off = 32
    for name in _LWF_ITEM_ARRAYS:
        if off + 8 > len(data):
            break
        items[name] = _st.unpack_from('<II', data, off)
        off += 8
    info['_items'] = items

    def _rs(name, fmt, fields):
        sec = items.get(name, (0, 0))
        if sec[1] == 0:
            return []
        esz = _st.calcsize(fmt)
        return [dict(zip(fields, _st.unpack_from(fmt, data, sec[0] + i * esz)))
                for i in range(sec[1]) if sec[0] + i * esz + esz <= len(data)]

    sb = items.get('stringBytes', (0, 0))
    sr = data[sb[0]:sb[0] + sb[1]] if sb[1] > 0 else b""
    sd = items.get('stringData', (0, 0))
    strings = []
    for i in range(sd[1]):
        so = _st.unpack_from('<I', data, sd[0] + i * 4)[0]
        end = sr.find(0, so) if so < len(sr) else so
        if end < 0:
            end = len(sr)
        try:
            strings.append(sr[so:end].decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            strings.append('')
    info['strings'] = strings

    info['_translates'] = _rs('translate', '<ff', ['x', 'y'])
    info['_matrices'] = _rs('matrix', '<ffffff', ['sx', 'sy', 'sk0', 'sk1', 'tx', 'ty'])
    info['_objects'] = _rs('objectData', '<II', ['type', 'id'])
    info['_textures'] = _rs('texture', '<IIiif', ['stringId', 'format', 'w', 'h', 'scale'])
    info['_fragments'] = _rs('textureFragment', '<IIiiiiiii', ['stringId', 'texId', 'rotated', 'x', 'y', 'u', 'v', 'w', 'h'])
    info['_bitmaps'] = _rs('bitmap', '<II', ['matId', 'fragId'])
    info['_gfxObjects'] = _rs('graphicObject', '<II', ['type', 'id'])
    info['_graphics'] = _rs('graphic', '<II', ['objOff', 'objs'])
    info['_places'] = _rs('place', '<iiii', ['depth', 'objId', 'instId', 'matId'])
    info['_ctrlMs'] = _rs('controlMoveM', '<II', ['placeId', 'matId'])
    info['_ctrlCs'] = _rs('controlMoveC', '<II', ['placeId', 'ctId'])
    info['_ctrlMCs'] = _rs('controlMoveMC', '<III', ['placeId', 'matId', 'ctId'])
    info['_controls'] = _rs('control', '<II', ['type', 'id'])
    info['_frames'] = _rs('frame', '<II', ['ctrlOff', 'ctrls'])
    info['_movies'] = _rs('movie', '<iIIIIII', ['depth', 'labOff', 'labs', 'frmOff', 'frms', 'ceOff', 'ces'])
    info['_linkages'] = _rs('movieLinkage', '<II', ['stringId', 'movieId'])

    for name, (_, count) in items.items():
        if count > 0 and name not in ('stringBytes', 'animationBytes', 'stringData'):
            info['counts'][name] = count

    img_exts = ('.png', '.btf', '.jpg', '.pvr', '.webp')
    texture_set = set()
    for t in info['_textures']:
        sname = strings[t['stringId']] if t['stringId'] < len(strings) else ''
        if sname:
            texture_set.add(sname)
    info['textures'] = sorted(texture_set)
    info['texture_resolved'] = {t: _decode_lwf_tex_name(t) for t in info['textures']}

    return info


def _lwf_get_mat(lwf, mid):
    if mid < 0:
        i = mid & 0x7FFFFFFF
        m = lwf['_matrices'][i] if i < len(lwf['_matrices']) else None
        return (m['sx'], m['sy'], m['sk0'], m['sk1'], m['tx'], m['ty']) if m else (1, 0, 0, 1, 0, 0)
    t = lwf['_translates'][mid] if mid < len(lwf['_translates']) else None
    return (1, 0, 0, 1, t['x'], t['y']) if t else (1, 0, 0, 1, 0, 0)


def _lwf_mat_mul(a, b):
    return (a[0]*b[0]+a[2]*b[1], a[1]*b[0]+a[3]*b[1],
            a[0]*b[2]+a[2]*b[3], a[1]*b[2]+a[3]*b[3],
            a[0]*b[4]+a[2]*b[5]+a[4], a[1]*b[4]+a[3]*b[5]+a[5])


def _render_lwf_movie(lwf, movie_id, frame_idx, tex_imgs, parent_mat, canvas, cx, cy, depth=0):
    """Recursively render an LWF movie frame onto canvas."""
    import math as _math
    if movie_id >= len(lwf['_movies']) or depth > 20:
        return
    movie = lwf['_movies'][movie_id]
    fi = movie['frmOff'] + min(frame_idx, max(0, movie['frms'] - 1))
    if fi >= len(lwf['_frames']):
        return
    frame = lwf['_frames'][fi]
    rlist = []
    for ci in range(frame['ctrlOff'], frame['ctrlOff'] + frame['ctrls']):
        if ci >= len(lwf['_controls']):
            break
        ct, cid = lwf['_controls'][ci]['type'], lwf['_controls'][ci]['id']
        pid = matid = None
        if ct == _LWF_CT_MOVE_M and cid < len(lwf['_ctrlMs']):
            pid, matid = lwf['_ctrlMs'][cid]['placeId'], lwf['_ctrlMs'][cid]['matId']
        elif ct == _LWF_CT_MOVE_C and cid < len(lwf['_ctrlCs']):
            pid = lwf['_ctrlCs'][cid]['placeId']
        elif ct == _LWF_CT_MOVE_MC and cid < len(lwf['_ctrlMCs']):
            pid, matid = lwf['_ctrlMCs'][cid]['placeId'], lwf['_ctrlMCs'][cid]['matId']
        if pid is None or pid >= len(lwf['_places']):
            continue
        place = lwf['_places'][pid]
        mid = matid if matid is not None else place['matId']
        wm = _lwf_mat_mul(parent_mat, _lwf_get_mat(lwf, mid))
        oid = place['objId'] & 0x7FFFFFFF if place['objId'] < 0 else place['objId']
        if oid >= len(lwf['_objects']):
            continue
        obj = lwf['_objects'][oid]
        if obj['type'] == _LWF_OT_BITMAP:
            b = lwf['_bitmaps'][obj['id']] if obj['id'] < len(lwf['_bitmaps']) else None
            if b:
                fm = _lwf_mat_mul(wm, _lwf_get_mat(lwf, b['matId']))
                f = lwf['_fragments'][b['fragId']] if b['fragId'] < len(lwf['_fragments']) else None
                if f:
                    t = lwf['_textures'][f['texId']] if f['texId'] < len(lwf['_textures']) else None
                    if t:
                        sn = lwf['strings'][t['stringId']] if t['stringId'] < len(lwf['strings']) else ''
                        rlist.append((place['depth'], sn, f, fm))
        elif obj['type'] == _LWF_OT_GRAPHIC:
            g = lwf['_graphics'][obj['id']] if obj['id'] < len(lwf['_graphics']) else None
            if g:
                for gi in range(g['objOff'], g['objOff'] + g['objs']):
                    go = lwf['_gfxObjects'][gi] if gi < len(lwf['_gfxObjects']) else None
                    if go and go['type'] == _LWF_OT_BITMAP:
                        b = lwf['_bitmaps'][go['id']] if go['id'] < len(lwf['_bitmaps']) else None
                        if b:
                            fm = _lwf_mat_mul(wm, _lwf_get_mat(lwf, b['matId']))
                            f = lwf['_fragments'][b['fragId']] if b['fragId'] < len(lwf['_fragments']) else None
                            if f:
                                t = lwf['_textures'][f['texId']] if f['texId'] < len(lwf['_textures']) else None
                                if t:
                                    sn = lwf['strings'][t['stringId']] if t['stringId'] < len(lwf['strings']) else ''
                                    rlist.append((place['depth'], sn, f, fm))
        elif obj['type'] == _LWF_OT_MOVIE:
            _render_lwf_movie(lwf, obj['id'], frame_idx, tex_imgs, wm, canvas, cx, cy, depth + 1)
    rlist.sort(key=lambda x: x[0])
    for _, sn, frag, mat in rlist:
        dec = _decode_lwf_tex_name(sn)
        img = tex_imgs.get(dec) or tex_imgs.get(sn) or tex_imgs.get(dec.rsplit('/', 1)[-1] if '/' in dec else dec)
        if not img:
            continue
        u, v, w, h = frag['u'], frag['v'], frag['w'], frag['h']
        sp = img.crop((u, v, u + w, v + h)) if w > 0 and h > 0 else img
        sx = _math.sqrt(mat[0]**2 + mat[1]**2)
        sy = _math.sqrt(mat[2]**2 + mat[3]**2)
        nw, nh = max(1, int(sp.width * sx)), max(1, int(sp.height * sy))
        if (nw, nh) != sp.size:
            sp = sp.resize((nw, nh), Image.BILINEAR)
        dx = cx + int(mat[4]) - nw // 2
        dy = cy - int(mat[5]) - nh // 2
        sx2, sy2 = 0, 0
        if dx < 0:
            sx2 = -dx; dx = 0
        if dy < 0:
            sy2 = -dy; dy = 0
        cw2 = min(sp.width - sx2, canvas.width - dx)
        ch2 = min(sp.height - sy2, canvas.height - dy)
        if cw2 > 0 and ch2 > 0:
            canvas.alpha_composite(sp.crop((sx2, sy2, sx2 + cw2, sy2 + ch2)), (dx, dy))


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
    rotation = float(opts.get('rotation', 0))
    scale_x = float(opts.get('scaleX', 1))
    scale_y = float(opts.get('scaleY', 1))
    flip_x = bool(opts.get('flipX', False))
    flip_y = bool(opts.get('flipY', False))
    opacity = int(opts.get('opacity', 255))

    return x, y, w, h, ax, ay, tex_path, cn, nm, s9, s9_x, s9_y, s9_w, s9_h, rotation, scale_x, scale_y, flip_x, flip_y, opacity


def _cs_bounding_box(node, px=0, py=0, show_hidden=False):
    """Compute the bounding box of widgets in the tree. Returns (min_x, min_y, max_x, max_y) in cocos2d world coords."""
    if not isinstance(node, dict):
        return (px, py, px, py)
    x, y, w, h, ax, ay, *_ = _cs_widget_props(node)
    awx = px + x
    awy = py + y
    opts = node.get('options', node)
    if not show_hidden and not opts.get('visible', True):
        min_x, min_y = awx, awy
        max_x, max_y = awx, awy
    else:
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


def _parse_plist(plist_data: str):
    """Parse a CocoStudio plist atlas. Returns (frames_list, texture_filename).
    frames_list: [(name, x, y, w, h, orig_w, orig_h, off_x, off_y), ...]
    texture_filename: str from metadata (e.g. 'LoadingAnimation0.png')
    """
    import xml.etree.ElementTree as _ET
    root = _ET.fromstring(plist_data)
    top_dict = root.find("dict")
    if top_dict is None:
        return [], ""
    top_children = list(top_dict)

    frames_dict = None
    tex_filename = ""
    for i, child in enumerate(top_children):
        if child.tag != "key" or i + 1 >= len(top_children):
            continue
        if child.text == "frames":
            frames_dict = top_children[i + 1]
        elif child.text == "metadata":
            meta = top_children[i + 1]
            mc = list(meta)
            for j in range(0, len(mc), 2):
                if j + 1 < len(mc) and mc[j].tag == "key" and mc[j].text == "textureFileName":
                    tex_filename = mc[j + 1].text or ""

    if frames_dict is None:
        return [], tex_filename
    children = list(frames_dict)
    result = []
    for i in range(0, len(children), 2):
        if i + 1 >= len(children) or children[i].tag != "key":
            continue
        fname = children[i].text
        fd = children[i + 1]
        props = {}
        fc = list(fd)
        for j in range(0, len(fc), 2):
            if j + 1 < len(fc) and fc[j].tag == "key":
                v = fc[j + 1]
                if v.tag == "integer":
                    props[fc[j].text] = int(v.text)
                elif v.tag == "real":
                    props[fc[j].text] = float(v.text)
        result.append((fname, props.get("x", 0), props.get("y", 0),
                        props.get("width", 0), props.get("height", 0),
                        props.get("originalWidth", props.get("width", 0)),
                        props.get("originalHeight", props.get("height", 0)),
                        props.get("offsetX", 0), props.get("offsetY", 0)))
    return result, tex_filename


def _parse_plist_frames(plist_data: str) -> list:
    """Backwards-compatible wrapper. Returns list of (name, x, y, w, h)."""
    frames, _ = _parse_plist(plist_data)
    return [(f[0], f[1], f[2], f[3], f[4]) for f in frames]


def _parse_exportjson(obj):
    """Parse an ExportJson and return (armature, animation, texture_data, config_plists, config_pngs)."""
    armature = obj.get('armature_data', [{}])[0] if obj.get('armature_data') else {}
    anim = obj.get('animation_data', [{}])[0] if obj.get('animation_data') else {}
    return (armature, anim, obj.get('texture_data', []),
            obj.get('config_file_path', []), obj.get('config_png_path', []))


def _detect_exportjson(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    return 'armature_data' in obj and 'animation_data' in obj and 'config_file_path' in obj


def _apply_tween_easing(t, twe):
    """Apply CocoStudio tween easing to interpolation factor t (0-1)."""
    import math as _m
    if twe == 0 or t <= 0 or t >= 1:
        return t
    if twe == 1:
        return 1 - _m.cos(t * _m.pi / 2)
    if twe == 2:
        return _m.sin(t * _m.pi / 2)
    if twe == 3:
        return -(_m.cos(_m.pi * t) - 1) / 2
    if twe == 4:
        return t * t
    if twe == 5:
        return t * (2 - t)
    if twe == 6:
        return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2
    if twe == 7:
        return t * t * t
    if twe == 8:
        return 1 - (1 - t) ** 3
    if twe == 9:
        return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2
    if twe == 10:
        return t ** 4
    if twe == 11:
        return 1 - (1 - t) ** 4
    if twe == 12:
        return 8 * t ** 4 if t < 0.5 else 1 - (-2 * t + 2) ** 4 / 2
    return t


def _interp_bone_keyframe(mov_bone, frame_idx):
    """Interpolate a bone's keyframe data at a given frame."""
    frames = mov_bone.get('frame_data', [])
    if not frames:
        return None
    dl = mov_bone.get('dl', 0)
    adj_frame = frame_idx - dl
    prev_kf = frames[0]
    next_kf = frames[0]
    for i, kf in enumerate(frames):
        if kf['fi'] <= adj_frame:
            prev_kf = kf
            next_kf = frames[i + 1] if i + 1 < len(frames) else kf
        else:
            next_kf = kf
            break
    span = next_kf['fi'] - prev_kf['fi']
    t = max(0.0, min(1.0, (adj_frame - prev_kf['fi']) / span)) if span > 0 else 0
    twe = prev_kf.get('twE', 0)
    if twe != 0:
        t = _apply_tween_easing(t, twe)
    def _lerp(a, b):
        return a + (b - a) * t
    if prev_kf.get('tweenFrame', True) and span > 0:
        ix = _lerp(prev_kf.get('x', 0), next_kf.get('x', 0))
        iy = _lerp(prev_kf.get('y', 0), next_kf.get('y', 0))
        icx = _lerp(prev_kf.get('cX', 1), next_kf.get('cX', 1))
        icy = _lerp(prev_kf.get('cY', 1), next_kf.get('cY', 1))
        ikx = _lerp(prev_kf.get('kX', 0), next_kf.get('kX', 0))
        iky = _lerp(prev_kf.get('kY', 0), next_kf.get('kY', 0))
        pc = prev_kf.get('color', {'a': 255, 'r': 255, 'g': 255, 'b': 255})
        nc = next_kf.get('color', {'a': 255, 'r': 255, 'g': 255, 'b': 255})
        ia = int(_lerp(pc.get('a', 255), nc.get('a', 255)))
        ir = int(_lerp(pc.get('r', 255), nc.get('r', 255)))
        ig = int(_lerp(pc.get('g', 255), nc.get('g', 255)))
        ib = int(_lerp(pc.get('b', 255), nc.get('b', 255)))
    else:
        ix, iy = prev_kf.get('x', 0), prev_kf.get('y', 0)
        icx, icy = prev_kf.get('cX', 1), prev_kf.get('cY', 1)
        ikx, iky = prev_kf.get('kX', 0), prev_kf.get('kY', 0)
        c_ = prev_kf.get('color', {'a': 255, 'r': 255, 'g': 255, 'b': 255})
        ia = c_.get('a', 255)
        ir, ig, ib = c_.get('r', 255), c_.get('g', 255), c_.get('b', 255)
    di = prev_kf.get('dI', 0)
    bd_src = prev_kf.get('bd_src', 1)
    bd_dst = prev_kf.get('bd_dst', 771)
    return (ix, iy, icx, icy, ikx, iky, di, ia, ir, ig, ib, bd_src, bd_dst)


def _render_anim_frame(anim_data, armature, sprites, frame_idx, canvas_size=(200, 200), texture_data=None):
    """Render a single frame of an ExportJson armature animation."""
    if not anim_data.get('mov_data'):
        return Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    cx, cy = canvas_size[0] // 2, canvas_size[1] // 2
    movement = anim_data['mov_data'][0]
    bone_map = {b['name']: b for b in armature.get('bone_data', [])}
    mov_bone_map = {mb['name']: mb for mb in movement.get('mov_bone_data', [])}
    tex_pivot = {}
    if texture_data:
        for td in texture_data:
            tex_pivot[td.get('name', '') + '.png'] = (td.get('pX', 0.5), td.get('pY', 0.5))

    import math as _math
    bone_world = {}

    def get_bone_world(bone_name):
        """Returns (world_x, world_y, world_rotation_radians)."""
        if bone_name in bone_world:
            return bone_world[bone_name]
        bone = bone_map.get(bone_name)
        if not bone:
            bone_world[bone_name] = (0, 0, 0)
            return (0, 0, 0)
        bx, by = bone.get('x', 0), bone.get('y', 0)
        bkx = bone.get('kX', 0)
        mb = mov_bone_map.get(bone_name)
        if mb:
            interp = _interp_bone_keyframe(mb, frame_idx)
            if interp:
                bx += interp[0]
                by += interp[1]
                bkx += interp[4]
        parent = bone.get('parent', '')
        if parent:
            px, py, pr = get_bone_world(parent)
            if abs(pr) > 0.001:
                cos_r = _math.cos(pr)
                sin_r = _math.sin(pr)
                rx = bx * cos_r - by * sin_r
                ry = bx * sin_r + by * cos_r
                bx, by = rx, ry
            bx += px
            by += py
            bkx += pr
        bone_world[bone_name] = (bx, by, bkx)
        return (bx, by, bkx)

    render_list = []
    for mov_bone in movement.get('mov_bone_data', []):
        bone = bone_map.get(mov_bone['name'])
        if not bone:
            continue
        interp = _interp_bone_keyframe(mov_bone, frame_idx)
        if not interp:
            continue
        _, _, icx, icy, ikx, iky, di, ia, ir, ig, ib, bd_src, bd_dst = interp

        display_data = bone.get('display_data', [])
        if di < 0 or di >= len(display_data):
            continue
        sprite_name = display_data[di]['name']
        sprite_img = sprites.get(sprite_name)
        if sprite_img is None:
            continue

        skin = display_data[di].get('skin_data', [{}])[0]
        skin_kx = skin.get('kX', 0)
        wx, wy, world_rot = get_bone_world(mov_bone['name'])
        sx_off, sy_off = skin.get('x', 0), skin.get('y', 0)
        total_rot = world_rot + skin_kx
        if abs(total_rot) > 0.001:
            cos_r = _math.cos(total_rot)
            sin_r = _math.sin(total_rot)
            rx = sx_off * cos_r - sy_off * sin_r
            ry = sx_off * sin_r + sy_off * cos_r
            sx_off, sy_off = rx, ry
        final_x = wx + sx_off
        final_y = -(wy + sy_off)
        bone_z = bone.get('z', 0)
        rot_deg = _math.degrees(total_rot)
        rough_half = max(sprite_img.size[0], sprite_img.size[1]) * max(abs(icx), abs(icy)) + 200
        if (cx + final_x + rough_half < 0 or cx + final_x - rough_half > canvas_size[0] or
            cy + final_y + rough_half < 0 or cy + final_y - rough_half > canvas_size[1]):
            continue
        blend = 'add' if bd_src == 1 and bd_dst == 1 else 'normal'
        render_list.append((bone_z, sprite_img, final_x, final_y,
                            abs(icx), abs(icy), icx < 0, icy < 0, rot_deg, ia, ir, ig, ib, blend, sprite_name))

    _sprite_cache = {}
    render_list.sort(key=lambda r: r[0])
    for z, sprite, px, py, sx, sy, flip_h, flip_v, rot_deg, alpha, r, g, b, blend, sprite_name in render_list:
        qsx = round(sx * 20) / 20
        qsy = round(sy * 20) / 20
        qrot = round(rot_deg * 2) / 2
        cache_key = (sprite_name, int(qsx * 100), int(qsy * 100), flip_h, flip_v, int(qrot * 10))
        if alpha == 0:
            continue
        if cache_key in _sprite_cache:
            img = _sprite_cache[cache_key]
        else:
            img = sprite
            w, h = img.size
            nw, nh = max(1, int(w * qsx)), max(1, int(h * qsy))
            if (nw, nh) != (w, h):
                img = img.resize((nw, nh), Image.BILINEAR)
            if flip_h:
                img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            if flip_v:
                img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            if abs(rot_deg) > 0.1:
                img = img.rotate(-rot_deg, expand=True, resample=Image.BILINEAR)
            _sprite_cache[cache_key] = img
        if alpha < 250 or r < 250 or g < 250 or b < 250:
            img = ImageChops.multiply(img, Image.new("RGBA", img.size, (r, g, b, alpha)))
        pivot = tex_pivot.get(sprite_name, (0.5, 0.5))
        dx = cx + int(px) - int(img.width * pivot[0])
        dy = cy + int(py) - int(img.height * pivot[1])
        if dx + img.width <= 0 or dy + img.height <= 0 or dx >= canvas.width or dy >= canvas.height:
            continue
        src_x, src_y = 0, 0
        if dx < 0:
            src_x = -dx; dx = 0
        if dy < 0:
            src_y = -dy; dy = 0
        cw = min(img.width - src_x, canvas.width - dx)
        ch = min(img.height - src_y, canvas.height - dy)
        if cw > 0 and ch > 0:
            cropped = img.crop((src_x, src_y, src_x + cw, src_y + ch))
            if blend == 'add':
                region = canvas.crop((dx, dy, dx + cw, dy + ch))
                added = ImageChops.add(region, cropped)
                canvas.paste(added, (dx, dy))
            else:
                canvas.alpha_composite(cropped, (dx, dy))
    return canvas


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
    double_clicked = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background-color: {COLORS['bg_alt']}; border: none;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setWidget(self._label)

        self._pixmap: Optional[QPixmap] = None
        self._zoom: float = 1.0
        self._original_size: QSize = QSize(0, 0)
        self._size_text: str = ""
        self._pan_start = None

    def set_pixmap(self, pixmap: QPixmap, keep_zoom: bool = False):
        self._pixmap = pixmap
        self._original_size = pixmap.size()
        self._size_text = f"{pixmap.width()} x {pixmap.height()}"
        if not keep_zoom:
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
        if self._pixmap:
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

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._pan_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_start is not None:
            delta = event.position().toPoint() - self._pan_start
            self._pan_start = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pan_start is not None:
            self._pan_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._pan_start = None
        if self._pixmap and event.button() == Qt.MouseButton.LeftButton:
            pos = self._label.mapFrom(self.viewport(), event.position().toPoint())
            self.double_clicked.emit(int(pos.x()), int(pos.y()))
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Escape):
            self.double_clicked.emit(-1, event.key())
        else:
            super().keyPressEvent(event)

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
    progress = pyqtSignal(str, int, int)  # (message, current, total)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path
        self._canceled = False

    def run(self):
        try:
            self.progress.emit(f"Opening {os.path.basename(self._path)}...", 0, 100)
            container = KHUxBGADContainer(self._path)
            file_size = os.path.getsize(self._path)

            def on_progress(count, pos, fs):
                if self._canceled:
                    raise InterruptedError("Load canceled")
                pos_mb = pos / (1024 * 1024)
                fs_mb = fs / (1024 * 1024)
                self.progress.emit(f"Reading entries... {count} entries  ({pos_mb:.0f}/{fs_mb:.0f} MB)", pos, fs)

            self.progress.emit("Analyzing file...", 0, file_size)
            entries = container.iter_entries(progress_callback=on_progress)
            if not self._canceled:
                self.progress.emit(f"Loaded {len(entries)} entries", len(entries), len(entries))
                self.finished.emit(container, entries, self._path)
        except InterruptedError:
            pass
        except Exception as e:
            if not self._canceled:
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

        from PyQt6.QtWidgets import QComboBox
        self._anim_mov_combo = QComboBox()
        self._anim_mov_combo.setFixedWidth(140)
        self._anim_mov_combo.setVisible(False)
        self._anim_mov_combo.currentIndexChanged.connect(self._anim_change_movement)
        preview_toolbar.addWidget(self._anim_mov_combo)

        self._anim_play_btn = QPushButton("Play")
        self._anim_play_btn.setFixedWidth(50)
        self._anim_play_btn.setVisible(False)
        self._anim_play_btn.clicked.connect(self._anim_toggle_play)
        preview_toolbar.addWidget(self._anim_play_btn)

        from PyQt6.QtWidgets import QSlider
        self._anim_slider = QSlider(Qt.Orientation.Horizontal)
        self._anim_slider.setFixedWidth(120)
        self._anim_slider.setVisible(False)
        self._anim_slider.valueChanged.connect(self._anim_seek)
        preview_toolbar.addWidget(self._anim_slider)

        self._anim_frame_label = QLabel("")
        self._anim_frame_label.setStyleSheet(f"color: {COLORS['fg_dim']}; font-size: 9pt;")
        self._anim_frame_label.setVisible(False)
        preview_toolbar.addWidget(self._anim_frame_label)

        self._scene_reset_btn = QPushButton("0")
        self._scene_reset_btn.setFixedWidth(24)
        self._scene_reset_btn.setToolTip("Reset to frame 0")
        self._scene_reset_btn.setVisible(False)
        self._scene_reset_btn.clicked.connect(self._scene_reset)
        preview_toolbar.addWidget(self._scene_reset_btn)

        self._scene_prev_btn = QPushButton("|<")
        self._scene_prev_btn.setFixedWidth(28)
        self._scene_prev_btn.setVisible(False)
        self._scene_prev_btn.clicked.connect(self._scene_step_back)
        preview_toolbar.addWidget(self._scene_prev_btn)

        self._scene_play_btn = QPushButton("Play")
        self._scene_play_btn.setFixedWidth(50)
        self._scene_play_btn.setVisible(False)
        self._scene_play_btn.clicked.connect(self._scene_toggle_play)
        preview_toolbar.addWidget(self._scene_play_btn)

        self._scene_next_btn = QPushButton(">|")
        self._scene_next_btn.setFixedWidth(28)
        self._scene_next_btn.setVisible(False)
        self._scene_next_btn.clicked.connect(self._scene_step_forward)
        preview_toolbar.addWidget(self._scene_next_btn)

        self._scene_frame_label = QLabel("")
        self._scene_frame_label.setStyleSheet(f"color: {COLORS['fg_dim']}; font-size: 9pt;")
        self._scene_frame_label.setVisible(False)
        preview_toolbar.addWidget(self._scene_frame_label)

        self._plist_prev_btn = QPushButton("<")
        self._plist_prev_btn.setFixedWidth(28)
        self._plist_prev_btn.setVisible(False)
        self._plist_prev_btn.clicked.connect(lambda: self._on_preview_interact(-1, Qt.Key.Key_Left))
        preview_toolbar.addWidget(self._plist_prev_btn)

        self._plist_grid_btn = QPushButton("Grid")
        self._plist_grid_btn.setFixedWidth(40)
        self._plist_grid_btn.setVisible(False)
        self._plist_grid_btn.clicked.connect(lambda: self._on_preview_interact(-1, Qt.Key.Key_Escape))
        preview_toolbar.addWidget(self._plist_grid_btn)

        self._plist_next_btn = QPushButton(">")
        self._plist_next_btn.setFixedWidth(28)
        self._plist_next_btn.setVisible(False)
        self._plist_next_btn.clicked.connect(lambda: self._on_preview_interact(-1, Qt.Key.Key_Right))
        preview_toolbar.addWidget(self._plist_next_btn)

        self._export_btn = QPushButton("Export")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export_clicked)
        preview_toolbar.addWidget(self._export_btn)

        center_layout.addLayout(preview_toolbar)

        # Preview notebook
        self._preview_notebook = QTabWidget()

        # Preview tab (images + audio stacked)
        from PyQt6.QtWidgets import QStackedWidget
        self._preview_stack = QStackedWidget()
        self._image_preview = ImagePreviewWidget()
        self._image_preview.zoom_changed.connect(self._on_zoom_changed)
        self._image_preview.double_clicked.connect(self._on_preview_interact)
        self._plist_sprites = []
        self._plist_atlas = None
        self._plist_sprite_idx = -1
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
        self._right_notebook = QTabWidget()

        # Properties tab
        self._props_text = PropertiesTextEdit()
        self._right_notebook.addTab(self._props_text, "Properties")

        # Hex view tab
        self._hex_text = StyledTextEdit(wrap=False)
        self._right_notebook.addTab(self._hex_text, "Hex View")

        # Preview controls tab (layers + draw toggles for UI entries)
        self._build_preview_controls_tab()

        self._splitter.addWidget(self._right_notebook)

        # Set initial splitter proportions (20% / 50% / 30%)
        QTimer.singleShot(50, self._set_initial_splitter)

    def _build_preview_controls_tab(self):
        from PyQt6.QtWidgets import QCheckBox, QScrollArea

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._show_hidden_cb = QCheckBox("Show Hidden")
        self._show_hidden_cb.setChecked(True)
        self._show_hidden_cb.toggled.connect(self._on_show_hidden_toggled)
        layout.addWidget(self._show_hidden_cb)

        sep0 = QFrame()
        sep0.setFrameShape(QFrame.Shape.HLine)
        sep0.setStyleSheet(f"color: {COLORS['border']};")
        layout.addWidget(sep0)

        # Draw toggles
        toggles_label = QLabel("Draw Options")
        toggles_label.setStyleSheet(f"font-weight: bold; color: {COLORS['fg_bright']};")
        layout.addWidget(toggles_label)

        self._draw_images_cb = QCheckBox("Draw Images")
        self._draw_images_cb.setChecked(True)
        self._draw_images_cb.toggled.connect(self._on_layer_changed)
        layout.addWidget(self._draw_images_cb)

        self._draw_text_cb = QCheckBox("Draw Text")
        self._draw_text_cb.setChecked(True)
        self._draw_text_cb.toggled.connect(self._on_layer_changed)
        layout.addWidget(self._draw_text_cb)

        self._draw_outlines_cb = QCheckBox("Draw Outlines")
        self._draw_outlines_cb.setChecked(True)
        self._draw_outlines_cb.toggled.connect(self._on_layer_changed)
        layout.addWidget(self._draw_outlines_cb)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {COLORS['border']};")
        layout.addWidget(sep)

        # Layers header
        layers_label = QLabel("Layers")
        layers_label.setStyleSheet(f"font-weight: bold; color: {COLORS['fg_bright']};")
        layout.addWidget(layers_label)

        # Scrollable layer list
        self._layers_scroll = QScrollArea()
        self._layers_scroll.setWidgetResizable(True)
        self._layers_scroll.setStyleSheet(f"border: none; background-color: {COLORS['bg']};")
        self._layers_widget = QWidget()
        self._layers_layout = QVBoxLayout(self._layers_widget)
        self._layers_layout.setContentsMargins(0, 0, 0, 0)
        self._layers_layout.setSpacing(2)
        self._layers_layout.addStretch()
        self._layers_scroll.setWidget(self._layers_widget)
        layout.addWidget(self._layers_scroll, 1)

        self._layer_checkboxes: List[tuple] = []

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {COLORS['border']};")
        layout.addWidget(sep2)

        anim_label = QLabel("Animations")
        anim_label.setStyleSheet(f"font-weight: bold; color: {COLORS['fg_bright']};")
        layout.addWidget(anim_label)

        self._scene_anims_scroll = QScrollArea()
        self._scene_anims_scroll.setWidgetResizable(True)
        self._scene_anims_scroll.setStyleSheet(f"border: none; background-color: {COLORS['bg']};")
        self._scene_anims_widget = QWidget()
        self._scene_anims_layout = QVBoxLayout(self._scene_anims_widget)
        self._scene_anims_layout.setContentsMargins(0, 0, 0, 0)
        self._scene_anims_layout.setSpacing(4)
        self._scene_anims_layout.addStretch()
        self._scene_anims_scroll.setWidget(self._scene_anims_widget)
        layout.addWidget(self._scene_anims_scroll, 1)

        self._scene_anim_controls: List[dict] = []

        self._preview_controls_tab_idx = self._right_notebook.addTab(container, "Preview")
        self._right_notebook.setTabVisible(self._preview_controls_tab_idx, False)

    def _populate_layer_list(self, node, depth=0):
        """Build layer checkboxes from the widget tree."""
        from PyQt6.QtWidgets import QCheckBox

        # Clear existing
        for cb, _ in self._layer_checkboxes:
            cb.setParent(None)
        self._layer_checkboxes.clear()

        # Remove stretch
        while self._layers_layout.count():
            item = self._layers_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        widgets = []
        self._collect_widgets(node, 0, widgets)

        for depth, cn, nm, visible in widgets:
            indent = "  " * depth
            label = f"{indent}[{cn}] {nm}" if nm else f"{indent}[{cn}]"
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.setStyleSheet(f"color: {COLORS['fg']}; font: 9pt 'Consolas'; padding: 1px 0px;")
            cb.toggled.connect(self._on_layer_changed)
            self._layers_layout.addWidget(cb)
            self._layer_checkboxes.append((cb, (cn, nm)))

        self._layers_layout.addStretch()
        self._update_layer_enabled_state()

    def _collect_widgets(self, node, depth, result):
        if not isinstance(node, dict):
            return
        opts = node.get('options', node)
        cn = node.get('classname', '?')
        nm = opts.get('name', node.get('name', ''))
        visible = opts.get('visible', True)
        result.append((depth, cn, nm, visible))
        for child in node.get('children', []):
            self._collect_widgets(child, depth + 1, result)

    def _update_layer_enabled_state(self):
        """Disable layer checkboxes when all relevant draw toggles are off."""
        draw_images = self._draw_images_cb.isChecked()
        draw_text = self._draw_text_cb.isChecked()
        draw_outlines = self._draw_outlines_cb.isChecked()
        any_draw = draw_images or draw_text or draw_outlines

        for cb, (cn, nm) in self._layer_checkboxes:
            if cn == "Label":
                relevant = draw_text or draw_outlines
            elif cn in ("ImageView", "Button"):
                relevant = draw_images or draw_outlines
            else:
                relevant = any_draw
            cb.setEnabled(relevant)

    def _clear_scene_anims(self):
        if hasattr(self, '_scene_anim_timer') and self._scene_anim_timer.isActive():
            self._scene_anim_timer.stop()
        for ctrl in self._scene_anim_controls:
            for w in ctrl.get('widgets', []):
                w.setParent(None)
        self._scene_anim_controls.clear()
        while self._scene_anims_layout.count():
            item = self._scene_anims_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._scene_anims_layout.addStretch()

    def _populate_scene_anims(self, obj):
        """Build animation controls for CCArmature components in a Scene file."""
        from PyQt6.QtWidgets import QComboBox

        for ctrl in self._scene_anim_controls:
            for w in ctrl.get('widgets', []):
                w.setParent(None)
        self._scene_anim_controls.clear()
        while self._scene_anims_layout.count():
            item = self._scene_anims_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        self._scene_anim_entries = []

        available_exports = []
        for ename in sorted(self.entry_map):
            if ename.endswith('.ExportJson'):
                available_exports.append(ename)

        def find_anims(gos, parent_x, parent_y):
            for go in gos:
                gx = parent_x + float(go.get('x', 0))
                gy = parent_y + float(go.get('y', 0))
                nm = go.get('name', '?')
                for comp in go.get('components', []):
                    if comp.get('classname') != 'CCArmature':
                        continue
                    fd = comp.get('fileData', {})
                    path = fd.get('path', '')
                    action = comp.get('selectedactionname', '') or ''
                    if action == 'None':
                        action = ''
                    self._scene_anim_entries.append((nm, path, gx, gy, action))
                find_anims(go.get('gameobjects', []), gx, gy)

        find_anims(obj.get('gameobjects', []), 0, 0)

        for i, (nm, path, gx, gy, action) in enumerate(self._scene_anim_entries):
            if path:
                entry = self._find_entry(path)
            else:
                entry = None

            anim_obj = None
            if entry:
                try:
                    anim_obj = json.loads(entry.data.decode('utf-8'))
                    if not _detect_exportjson(anim_obj):
                        anim_obj = None
                except (json.JSONDecodeError, ValueError):
                    pass

            row_widget = QWidget()
            row_layout = QVBoxLayout(row_widget)
            row_layout.setContentsMargins(2, 2, 2, 6)
            row_layout.setSpacing(2)

            path_label = path.split('/')[-1] if path else "(no file)"
            name_label = QLabel(f"{nm} — {path_label}")
            name_label.setStyleSheet(f"color: {COLORS['fg']}; font: 9pt 'Consolas';")
            row_layout.addWidget(name_label)

            # File selector for path-less entries
            file_combo = None
            if not anim_obj:
                file_row = QHBoxLayout()
                file_label = QLabel("File:")
                file_label.setStyleSheet(f"color: {COLORS['fg_dim']}; font-size: 9pt;")
                file_row.addWidget(file_label)
                file_combo = QComboBox()
                file_combo.addItem("(none)")
                for epath in available_exports:
                    file_combo.addItem(epath.split('/')[-1], epath)
                file_combo.currentIndexChanged.connect(lambda idx, si=i: self._on_scene_anim_file_changed(si, idx))
                file_row.addWidget(file_combo, 1)
                row_layout.addLayout(file_row)

            controls_row = QHBoxLayout()
            mode_combo = QComboBox()
            mode_combo.addItems(["Off", "Last Frame", "Play Once", "Loop"])
            default_mode = 0 if not anim_obj else (3 if action else 1)
            mode_combo.setCurrentIndex(default_mode)
            mode_combo.setFixedWidth(90)
            mode_combo.currentIndexChanged.connect(self._on_scene_anim_changed)
            controls_row.addWidget(mode_combo)

            mov_combo = QComboBox()
            if anim_obj:
                armature, anim_data, tex_data, plists, pngs = _parse_exportjson(anim_obj)
                movs = anim_data.get('mov_data', [])
                best_idx = 0
                best_bones = 0
                action_matched = False
                for mi, mov in enumerate(movs):
                    bc = len(mov.get('mov_bone_data', []))
                    mov_combo.addItem(f"{mov.get('name', f'mov_{mi}')} ({mov.get('dr', 0)}f)")
                    if action and mov.get('name') == action:
                        best_idx = mi
                        action_matched = True
                    elif not action_matched and bc > best_bones:
                        best_bones = bc
                        best_idx = mi
                mov_combo.setCurrentIndex(best_idx)
            else:
                armature = {}
                anim_data = {}
                plists, pngs = [], []
            mov_combo.currentIndexChanged.connect(self._on_scene_anim_changed)
            controls_row.addWidget(mov_combo, 1)

            row_layout.addLayout(controls_row)
            self._scene_anims_layout.insertWidget(self._scene_anims_layout.count() - 1, row_widget)

            sprites = {}
            if HAS_BTF and anim_obj:
                for pp, pn in zip(plists, pngs):
                    pe = self._find_entry(pp)
                    pne = self._find_entry(pn)
                    if pe and pne and len(pne.data) >= 4 and pne.data[:4] == b'\x89BTF':
                        try:
                            frames = _parse_plist_frames(pe.data.decode('utf-8-sig'))
                            atlas = KHUxBTF.from_bytes(pne.data).decode(use_canvas=True)
                            for fn, fx, fy, fw, fh in frames:
                                if fw > 0 and fh > 0:
                                    sprites[fn] = atlas.crop((fx, fy, fx + fw, fy + fh)).convert("RGBA")
                        except Exception:
                            pass

            self._scene_anim_controls.append({
                'widgets': [row_widget],
                'file_combo': file_combo,
                'mode_combo': mode_combo,
                'mov_combo': mov_combo,
                'armature': armature,
                'anim_data': anim_data,
                'texture_data': tex_data if anim_obj else [],
                'sprites': sprites,
                'gx': gx,
                'gy': gy,
                'frame': 0,
            })

    def _on_scene_anim_file_changed(self, scene_idx, combo_idx):
        """Handle user selecting an ExportJson file for a path-less CCArmature."""
        if scene_idx >= len(self._scene_anim_controls):
            return
        ctrl = self._scene_anim_controls[scene_idx]
        fc = ctrl.get('file_combo')
        if not fc or combo_idx <= 0:
            ctrl['armature'] = {}
            ctrl['anim_data'] = {}
            ctrl['sprites'] = {}
            ctrl['mov_combo'].clear()
            self._on_scene_anim_changed()
            return
        epath = fc.itemData(combo_idx)
        entry = self._find_entry(epath)
        if not entry:
            return
        try:
            anim_obj = json.loads(entry.data.decode('utf-8'))
        except (json.JSONDecodeError, ValueError):
            return
        if not _detect_exportjson(anim_obj):
            return
        armature, anim_data, tex_data, plists, pngs = _parse_exportjson(anim_obj)
        ctrl['armature'] = armature
        ctrl['anim_data'] = anim_data
        ctrl['mov_combo'].blockSignals(True)
        ctrl['mov_combo'].clear()
        movs = anim_data.get('mov_data', [])
        best_idx = 0
        best_bones = 0
        for mi, mov in enumerate(movs):
            bc = len(mov.get('mov_bone_data', []))
            ctrl['mov_combo'].addItem(f"{mov.get('name', f'mov_{mi}')} ({mov.get('dr', 0)}f)")
            if bc > best_bones:
                best_bones = bc
                best_idx = mi
        ctrl['mov_combo'].setCurrentIndex(best_idx)
        ctrl['mov_combo'].blockSignals(False)

        sprites = {}
        if HAS_BTF:
            for pp, pn in zip(plists, pngs):
                pe = self._find_entry(pp)
                pne = self._find_entry(pn)
                if pe and pne and len(pne.data) >= 4 and pne.data[:4] == b'\x89BTF':
                    try:
                        frames = _parse_plist_frames(pe.data.decode('utf-8-sig'))
                        atlas = KHUxBTF.from_bytes(pne.data).decode(use_canvas=True)
                        for fn, fx, fy, fw, fh in frames:
                            if fw > 0 and fh > 0:
                                sprites[fn] = atlas.crop((fx, fy, fx + fw, fy + fh)).convert("RGBA")
                    except Exception:
                        pass
        ctrl['sprites'] = sprites
        ctrl['texture_data'] = tex_data
        ctrl['mode_combo'].setCurrentIndex(1)
        self._on_scene_anim_changed()

    def _scene_reset(self):
        if hasattr(self, '_scene_anim_timer') and self._scene_anim_timer.isActive():
            self._scene_anim_timer.stop()
            self._scene_play_btn.setText("Play")
        self._scene_playing_frame = 0
        self._scene_set_frame(0)

    def _scene_toggle_play(self):
        if hasattr(self, '_scene_anim_timer') and self._scene_anim_timer.isActive():
            self._scene_anim_timer.stop()
            self._scene_play_btn.setText("Play")
        else:
            self._scene_playing_frame = getattr(self, '_scene_playing_frame', 0)
            if not hasattr(self, '_scene_anim_timer'):
                self._scene_anim_timer = QTimer(self)
                self._scene_anim_timer.timeout.connect(self._scene_anim_tick)
            self._scene_anim_timer.start(17)
            self._scene_play_btn.setText("Pause")

    def _scene_step_forward(self):
        self._scene_playing_frame = getattr(self, '_scene_playing_frame', 0) + 1
        self._scene_set_frame(self._scene_playing_frame)

    def _scene_step_back(self):
        self._scene_playing_frame = max(0, getattr(self, '_scene_playing_frame', 0) - 1)
        self._scene_set_frame(self._scene_playing_frame)

    def _scene_loop_point(self):
        """Compute LCM of all looping animation durations — the frame where all loops sync to 0."""
        from math import gcd
        durations = []
        for ctrl in self._scene_anim_controls:
            if ctrl['mode_combo'].currentIndex() != 3:
                continue
            mov_idx = ctrl['mov_combo'].currentIndex()
            movs = ctrl['anim_data'].get('mov_data', [])
            if mov_idx < len(movs):
                durations.append(movs[mov_idx].get('dr', 1))
        if not durations:
            return 0
        lcm = durations[0]
        for d in durations[1:]:
            lcm = lcm * d // gcd(lcm, d)
        return lcm

    def _scene_set_frame(self, frame):
        loop_pt = self._scene_loop_point()
        if loop_pt > 0 and frame >= loop_pt:
            frame = frame % loop_pt
            self._scene_playing_frame = frame
        else:
            max_dr = max((ctrl['anim_data'].get('mov_data', [{}])[ctrl['mov_combo'].currentIndex()].get('dr', 1)
                          for ctrl in self._scene_anim_controls
                          if ctrl['mode_combo'].currentIndex() != 0 and ctrl['anim_data'].get('mov_data')),
                         default=1)
            cap = max_dr * 5
            if frame >= cap:
                frame = cap
                self._scene_playing_frame = cap
        for ctrl in self._scene_anim_controls:
            mode = ctrl['mode_combo'].currentIndex()
            if mode == 0:
                continue
            mov_idx = ctrl['mov_combo'].currentIndex()
            movs = ctrl['anim_data'].get('mov_data', [])
            if mov_idx >= len(movs):
                continue
            dr = movs[mov_idx].get('dr', 1)
            if mode == 1:
                ctrl['frame'] = dr - 1
            elif mode == 3:
                ctrl['frame'] = frame % dr
            else:
                ctrl['frame'] = min(frame, dr - 1)
        self._render_scene_with_anims()
        self._scene_frame_label.setText(f"F: {frame}")

    def _on_scene_anim_changed(self, _idx=None):
        for ctrl in self._scene_anim_controls:
            mode = ctrl['mode_combo'].currentIndex()
            if mode == 1:
                mov_idx = ctrl['mov_combo'].currentIndex()
                movs = ctrl['anim_data'].get('mov_data', [])
                if mov_idx < len(movs):
                    ctrl['frame'] = movs[mov_idx].get('dr', 1) - 1
                else:
                    ctrl['frame'] = 0
            else:
                ctrl['frame'] = 0
        if hasattr(self, '_scene_anim_timer') and self._scene_anim_timer.isActive():
            self._scene_anim_timer.stop()
        any_playing = any(
            ctrl['mode_combo'].currentIndex() in (2, 3)
            for ctrl in self._scene_anim_controls
        )
        if any_playing:
            if not hasattr(self, '_scene_anim_timer'):
                self._scene_anim_timer = QTimer(self)
                self._scene_anim_timer.timeout.connect(self._scene_anim_tick)
            self._scene_anim_timer.start(17)
        self._render_scene_with_anims()

    def _scene_anim_tick(self):
        self._scene_playing_frame = getattr(self, '_scene_playing_frame', 0) + 1
        self._scene_set_frame(self._scene_playing_frame)

    def _render_scene_with_anims(self):
        scene_obj = getattr(self, '_scene_obj', None)
        if not scene_obj:
            return
        canvas = Image.new('RGBA', (960, 640), (40, 40, 42, 255))
        show_hidden = bool(getattr(self, '_show_hidden_cb', None) and self._show_hidden_cb.isChecked())
        anim_idx = [0]

        def render_gameobjects(gos, parent_x, parent_y):
            for go in gos:
                if not show_hidden and not go.get('visible', 1):
                    # Still count CCArmature components to keep anim_idx in sync
                    for comp in go.get('components', []):
                        if comp.get('classname') == 'CCArmature':
                            anim_idx[0] += 1
                    continue
                gx = parent_x + float(go.get('x', 0))
                gy = parent_y + float(go.get('y', 0))
                for comp in go.get('components', []):
                    cn = comp.get('classname', '')
                    if cn == 'GUIComponent':
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
                    elif cn == 'CCArmature':
                        ci = anim_idx[0]
                        anim_idx[0] += 1
                        if ci >= len(self._scene_anim_controls):
                            continue
                        ctrl = self._scene_anim_controls[ci]
                        mode = ctrl['mode_combo'].currentIndex()
                        if mode == 0:
                            continue
                        mov_idx = ctrl['mov_combo'].currentIndex()
                        movs = ctrl['anim_data'].get('mov_data', [])
                        if not movs or mov_idx >= len(movs):
                            continue
                        mov = movs[mov_idx]
                        dr = mov.get('dr', 1)
                        frame = ctrl['frame']
                        anim_single = {'mov_data': [mov]}
                        frame_img = _render_anim_frame(anim_single, ctrl['armature'],
                                                        ctrl['sprites'], frame,
                                                        canvas_size=(960, 640),
                                                        texture_data=ctrl.get('texture_data'))
                        offset_x = int(gx) - 480
                        offset_y = -(int(gy) - 320)
                        dx, dy = offset_x, offset_y
                        sx, sy = 0, 0
                        if dx < 0:
                            sx = -dx; dx = 0
                        if dy < 0:
                            sy = -dy; dy = 0
                        cw = min(frame_img.width - sx, canvas.width - dx)
                        ch = min(frame_img.height - sy, canvas.height - dy)
                        if cw > 0 and ch > 0:
                            canvas.alpha_composite(frame_img.crop((sx, sy, sx + cw, sy + ch)), (dx, dy))
                render_gameobjects(go.get('gameobjects', []), gx, gy)

        render_gameobjects(scene_obj.get('gameobjects', []), 0, 0)

        self._current_pil_image = canvas
        self._image_preview.set_pixmap(_pil_image_to_qpixmap(canvas), keep_zoom=True)

    def _on_layer_changed(self, _checked=None):
        self._update_layer_enabled_state()
        if self.current_entry:
            fmt = self.entry_formats.get(self.current_entry.name, "")
            if fmt == "scene" and getattr(self, '_scene_obj', None):
                self._render_scene_with_anims()
            elif fmt in ("ui", "scene"):
                self._render_cocostudio_visual(self.current_entry)

    def _get_layer_visibility(self):
        """Return dict mapping (classname, name) to checkbox state."""
        vis = {}
        idx = 0
        for cb, (cn, nm) in self._layer_checkboxes:
            vis[idx] = cb.isChecked() and cb.isEnabled()
            idx += 1
        return vis

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

    def _on_preview_interact(self, x: int, y: int):
        if not self._plist_sprites:
            return
        if x == -1:
            key_val = y
            if key_val == Qt.Key.Key_Escape:
                self._plist_sprite_idx = -1
                self._render_plist_grid()
            elif key_val == Qt.Key.Key_Left and self._plist_sprite_idx >= 0:
                self._render_plist_sprite_detail(max(0, self._plist_sprite_idx - 1))
            elif key_val == Qt.Key.Key_Right:
                nxt = self._plist_sprite_idx + 1 if self._plist_sprite_idx >= 0 else 0
                if nxt < len(self._plist_sprites):
                    self._render_plist_sprite_detail(nxt)
            return
        if self._plist_sprite_idx >= 0:
            self._plist_sprite_idx = -1
            self._render_plist_grid()
            return
        cols = getattr(self, '_plist_grid_cols', 1)
        cw, ch = getattr(self, '_plist_grid_cell', (100, 100))
        title_h = getattr(self, '_plist_grid_title_h', 24)
        pad = getattr(self, '_plist_grid_padding', 10)
        col = (x - pad) // cw
        row = (y - title_h - pad) // ch
        if col < 0 or row < 0 or col >= cols:
            return
        idx = row * cols + col
        if 0 <= idx < len(self._plist_sprites):
            self._render_plist_sprite_detail(idx)

    def _init_anim_player(self, entry: BGADEntry):
        """Initialize animation player for an ExportJson entry."""
        try:
            obj = json.loads(entry.data.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, ValueError):
            return
        armature, anim, tex_data, plists, pngs = _parse_exportjson(obj)
        if not anim.get('mov_data'):
            return

        sprites = {}
        if HAS_BTF:
            for plist_path, png_path in zip(plists, pngs):
                pe = self._find_entry(plist_path)
                pnge = self._find_entry(png_path)
                if pe and pnge and len(pnge.data) >= 4 and pnge.data[:4] == b'\x89BTF':
                    try:
                        frames = _parse_plist_frames(pe.data.decode("utf-8-sig"))
                        atlas = KHUxBTF.from_bytes(pnge.data).decode(use_canvas=True)
                        for name, x, y, w, h in frames:
                            if w > 0 and h > 0:
                                sprites[name] = atlas.crop((x, y, x + w, y + h)).convert("RGBA")
                    except Exception:
                        pass

        self._anim_armature = armature
        self._anim_data = anim
        self._anim_texture_data = tex_data
        self._anim_sprites = sprites
        movs = anim.get('mov_data', [])
        best_idx = 0
        best_bones = 0
        self._anim_mov_combo.blockSignals(True)
        self._anim_mov_combo.clear()
        for i, mov in enumerate(movs):
            bone_count = len(mov.get('mov_bone_data', []))
            label = f"{mov.get('name', f'mov_{i}')} ({mov.get('dr', 0)}f, {bone_count}b)"
            self._anim_mov_combo.addItem(label)
            if bone_count > best_bones:
                best_bones = bone_count
                best_idx = i
        self._anim_mov_combo.setCurrentIndex(best_idx)
        self._anim_mov_combo.blockSignals(False)

        self._anim_movement_idx = best_idx
        self._anim_dr = movs[best_idx].get('dr', 1)
        self._anim_loop = movs[best_idx].get('lp', False)
        self._anim_sc = movs[best_idx].get('sc', 1.0)
        self._anim_frame = 0
        self._anim_playing = False

        self._anim_slider.setRange(0, self._anim_dr - 1)
        self._anim_slider.setValue(0)
        self._anim_mov_combo.setVisible(len(movs) > 1)
        self._anim_play_btn.setVisible(True)
        self._anim_play_btn.setText("Play")
        self._anim_slider.setVisible(True)
        self._anim_frame_label.setVisible(True)

        if not hasattr(self, '_anim_timer'):
            self._anim_timer = QTimer(self)
            self._anim_timer.timeout.connect(self._anim_tick)

        self._anim_render_current()

    def _anim_change_movement(self, idx):
        if idx < 0 or not hasattr(self, '_anim_data'):
            return
        movs = self._anim_data.get('mov_data', [])
        if idx >= len(movs):
            return
        self._anim_movement_idx = idx
        self._anim_dr = movs[idx].get('dr', 1)
        self._anim_loop = movs[idx].get('lp', False)
        self._anim_sc = movs[idx].get('sc', 1.0)
        self._anim_frame = 0
        self._anim_slider.setRange(0, self._anim_dr - 1)
        self._anim_slider.setValue(0)
        self._anim_bg = None
        self._anim_cache = {}
        self._anim_render_current()

    def _anim_toggle_play(self):
        import time as _time
        if self._anim_playing:
            self._anim_playing = False
            self._anim_timer.stop()
            self._anim_play_btn.setText("Play")
        else:
            self._anim_playing = True
            start_frame = self._lwf_frame if getattr(self, '_lwf_info', None) else self._anim_frame
            self._anim_play_start = _time.perf_counter()
            self._anim_play_start_frame = start_frame
            self._anim_play_btn.setText("Pause")
            if not hasattr(self, '_anim_timer'):
                self._anim_timer = QTimer(self)
                self._anim_timer.timeout.connect(self._anim_tick)
            self._anim_timer.start(17)

    def _anim_tick(self):
        import time as _time
        is_lwf = bool(getattr(self, '_lwf_info', None))
        elapsed = _time.perf_counter() - self._anim_play_start
        fps = self._lwf_info.get('frameRate', 30) if is_lwf else 60
        sc = getattr(self, '_anim_sc', 1.0)
        target_frame = self._anim_play_start_frame + int(elapsed * fps * sc)
        dr = (getattr(self, '_lwf_total_frames', 1) if is_lwf else getattr(self, '_anim_dr', 1)) or 1
        if target_frame >= dr:
            target_frame = target_frame % dr
            self._anim_play_start = _time.perf_counter()
            self._anim_play_start_frame = target_frame
        self._anim_slider.blockSignals(True)
        self._anim_slider.setValue(target_frame)
        self._anim_slider.blockSignals(False)
        if is_lwf:
            self._lwf_frame = target_frame
            self._lwf_render_current()
            self._anim_frame_label.setText(f"{target_frame}/{dr - 1}")
        else:
            self._anim_frame = target_frame
            self._anim_render_current()

    def _anim_seek(self, value):
        if getattr(self, '_lwf_info', None):
            self._lwf_frame = value
            self._lwf_render_current()
            total = getattr(self, '_lwf_total_frames', 1)
            self._anim_frame_label.setText(f"{value}/{total - 1}")
            return
        self._anim_frame = value
        self._anim_render_current()

    def _anim_render_current(self):
        if not hasattr(self, '_anim_bg') or self._anim_bg is None:
            canvas_w, canvas_h = 960, 640
            self._anim_bg = Image.new("RGBA", (canvas_w, canvas_h), (30, 30, 30, 255))
            self._anim_canvas_size = (canvas_w, canvas_h)
        canvas_w, canvas_h = self._anim_canvas_size
        mov = self._anim_data['mov_data'][self._anim_movement_idx]
        anim_single = {'mov_data': [mov]}
        frame_img = _render_anim_frame(anim_single, self._anim_armature,
                                        self._anim_sprites, self._anim_frame,
                                        canvas_size=(canvas_w, canvas_h),
                                        texture_data=getattr(self, '_anim_texture_data', None))
        bg = self._anim_bg.copy()
        bg.alpha_composite(frame_img, (0, 0))
        self._current_pil_image = bg
        self._image_preview.set_pixmap(_pil_image_to_qpixmap(bg), keep_zoom=True)
        dr = self._anim_dr
        loop_str = " loop" if self._anim_loop else ""
        self._anim_frame_label.setText(f"{self._anim_frame}/{dr - 1}{loop_str}")

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

    def _cleanup_state(self):
        """Stop all timers and clear state from the previous file."""
        if hasattr(self, '_anim_timer') and self._anim_timer.isActive():
            self._anim_timer.stop()
        if hasattr(self, '_scene_anim_timer') and self._scene_anim_timer.isActive():
            self._scene_anim_timer.stop()
        self._anim_playing = False
        self._anim_sprites = {}
        self._anim_bg = None
        self._lwf_info = None
        self._lwf_textures = {}
        self._lwf_frame = 0
        self._scene_obj = None
        self._plist_sprites = []
        self._plist_atlas = None
        self._plist_sprite_idx = -1
        self._clear_scene_anims()
        self._image_preview.clear_image()
        self._audio_player.clear_audio()
        self._preview_text.clear()
        self._preview_hex.clear()
        self._current_pil_image = None
        self.current_entry = None

    def _load_file(self, path: str):
        if not os.path.exists(path):
            QMessageBox.critical(self, "Error", f"File not found:\n{path}")
            return

        self._cleanup_state()
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

        from PyQt6.QtWidgets import QProgressDialog
        self._load_progress = QProgressDialog("Opening file...", "Cancel", 0, 100, self)
        self._load_progress.setWindowTitle("Loading")
        self._load_progress.setMinimumDuration(0)
        self._load_progress.setValue(0)
        self._load_progress.canceled.connect(self._on_load_canceled)
        self._load_progress.show()

        self._loader = FileLoaderWorker(path)
        self._loader.progress.connect(self._on_load_progress)
        self._loader.error.connect(self._on_load_error)
        self._loader.finished.connect(self._on_load_finished)
        self._loader.start()

    def _on_load_canceled(self):
        if hasattr(self, '_loader') and self._loader:
            self._loader._canceled = True
        if hasattr(self, '_load_progress') and self._load_progress:
            self._load_progress.close()
            self._load_progress = None
        self._status_left.setText("Load canceled")
        self._loader = None

    def _on_load_progress(self, msg: str, current: int, total: int):
        if hasattr(self, '_load_progress') and self._load_progress:
            self._load_progress.setLabelText(msg)
            if total > 0:
                self._load_progress.setMaximum(100)
                self._load_progress.setValue(min(99, int(current * 100 / total)))
            else:
                self._load_progress.setMaximum(100)
                self._load_progress.setValue(0)
        self._status_left.setText(msg)

    def _on_load_error(self, msg: str):
        if hasattr(self, '_load_progress') and self._load_progress:
            self._load_progress.close()
            self._load_progress = None
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
        for ei, e in enumerate(entry_list):
            if ei % 500 == 0 and hasattr(self, '_load_progress') and self._load_progress:
                self._load_progress.setValue(ei)
                QApplication.processEvents()
            if e.name.lower().endswith(".ttf") and not _is_stub(e):
                self.entry_formats[e.name] = "ttf"
            elif e.data and len(e.data) >= 4:
                fmt = detect_format(e.data[:4])
                if fmt == "index" and _is_stub(e):
                    import struct as _struct
                    stub_val = _struct.unpack("<I", e.data[:4])[0]
                    if stub_val < len(real_table):
                        target_idx = real_table[stub_val]
                        target_data = entry_list[target_idx].data
                        real_fmt = detect_format(target_data[:min(64, len(target_data))])
                        if real_fmt in ("unknown", "index"):
                            ext = e.name.rsplit(".", 1)[-1].lower() if "." in e.name else ""
                            if ext in ("ttf", "lwf", "json", "txt", "plist"):
                                real_fmt = ext
                        self.entry_formats[e.name] = f"link:{real_fmt}"
                        self.entry_link_targets[e.name] = target_idx
                    else:
                        self.entry_formats[e.name] = "index"
                else:
                    if fmt in ("json", "text") and len(e.data) > 20:
                        try:
                            probe = json.loads(e.data.decode("utf-8", errors="replace"))
                            if _detect_exportjson(probe):
                                fmt = "anim"
                            elif probe.get('classname') == 'CCNode' and 'gameobjects' in probe:
                                fmt = "scene"
                            elif _detect_cocostudio(probe):
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

        if hasattr(self, '_load_progress') and self._load_progress:
            self._load_progress.setLabelText(f"Classifying {len(entries)} entries...")
            self._load_progress.setMaximum(len(entries))
            self._load_progress.setValue(0)
            QApplication.processEvents()

        fname = os.path.basename(path)
        self._file_label.setText(fname)
        self._file_label.setStyleSheet(f"color: {COLORS['fg_bright']};")

        if hasattr(self, '_load_progress') and self._load_progress:
            self._load_progress.setLabelText(f"Building tree ({len(entries)} entries)...")
            self._load_progress.setMaximum(100)
            self._load_progress.setValue(50)
            QApplication.processEvents()

        self._populate_tree()

        if hasattr(self, '_load_progress') and self._load_progress:
            self._load_progress.close()
            self._load_progress = None

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
        self._plist_sprites = []
        self._plist_atlas = None
        self._plist_sprite_idx = -1
        self._plist_prev_btn.setVisible(False)
        self._plist_grid_btn.setVisible(False)
        self._plist_next_btn.setVisible(False)
        self._anim_mov_combo.setVisible(False)
        self._anim_play_btn.setVisible(False)
        self._anim_slider.setVisible(False)
        self._anim_frame_label.setVisible(False)
        self._scene_reset_btn.setVisible(False)
        self._scene_prev_btn.setVisible(False)
        self._scene_play_btn.setVisible(False)
        self._scene_play_btn.setText("Play")
        self._scene_next_btn.setVisible(False)
        self._scene_frame_label.setVisible(False)
        if hasattr(self, '_anim_timer') and self._anim_timer.isActive():
            self._anim_timer.stop()
        if hasattr(self, '_scene_anim_timer') and self._scene_anim_timer.isActive():
            self._scene_anim_timer.stop()
        self._anim_playing = False
        self._anim_sprites = {}
        self._anim_bg = None
        self._scene_obj = None
        self._right_notebook.setTabVisible(self._preview_controls_tab_idx, False)
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
            if self._render_lwf_visual(entry):
                total = getattr(self, '_lwf_total_frames', 1)
                if total > 1:
                    self._anim_play_btn.setVisible(True)
                    self._anim_play_btn.setText("Play")
                    self._anim_slider.setVisible(True)
                    self._anim_slider.setRange(0, total - 1)
                    self._anim_slider.setValue(0)
                    self._anim_frame_label.setVisible(True)
                    self._anim_frame_label.setText(f"0/{total - 1}")
            self._preview_stack.setCurrentIndex(0)
            self._preview_notebook.setCurrentIndex(0)
            self._zoom_in_btn.setEnabled(True)
            self._zoom_out_btn.setEnabled(True)
        elif fmt == "anim":
            self._show_text_preview(entry)
            self._init_anim_player(entry)
            self._preview_stack.setCurrentIndex(0)
            self._preview_notebook.setCurrentIndex(0)
            self._zoom_in_btn.setEnabled(True)
            self._zoom_out_btn.setEnabled(True)
        elif fmt in ("scene", "ui"):
            self._show_text_preview(entry)
            try:
                obj = json.loads(entry.data.decode("utf-8", errors="replace"))
                root = _cs_get_root(obj)
                if isinstance(root, dict):
                    self._populate_layer_list(root)
                if fmt == "scene":
                    self._scene_obj = obj
                    self._scene_playing_frame = 0
                    self._populate_scene_anims(obj)
                    self._render_scene_with_anims()
                    self._on_scene_anim_changed()
                    self._scene_reset_btn.setVisible(True)
                    self._scene_prev_btn.setVisible(True)
                    self._scene_play_btn.setVisible(True)
                    self._scene_next_btn.setVisible(True)
                    self._scene_frame_label.setVisible(True)
                    self._scene_frame_label.setText("F: 0")
                else:
                    self._clear_scene_anims()
                    self._render_cocostudio_visual(entry)
            except Exception:
                pass
            self._right_notebook.setTabVisible(self._preview_controls_tab_idx, True)
            self._right_notebook.setCurrentIndex(self._preview_controls_tab_idx)
            self._preview_stack.setCurrentIndex(0)
            self._preview_notebook.setCurrentIndex(0)
            self._zoom_in_btn.setEnabled(True)
            self._zoom_out_btn.setEnabled(True)
        elif fmt == "plist":
            self._show_plist_text_preview(entry)
            if self._render_plist_visual(entry):
                self._preview_stack.setCurrentIndex(0)
                self._preview_notebook.setCurrentIndex(0)
                self._zoom_in_btn.setEnabled(True)
                self._zoom_out_btn.setEnabled(True)
            else:
                self._preview_notebook.setCurrentIndex(1)
                self._zoom_in_btn.setEnabled(False)
                self._zoom_out_btn.setEnabled(False)
        elif fmt in ("json",) or self._is_text_data(entry.data):
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

    def _render_plist_visual(self, entry: BGADEntry) -> bool:
        """Render plist sprite atlas as a grid of cropped sprites."""
        if not HAS_PIL or not HAS_BTF:
            return False
        try:
            plist_data = entry.data.decode("utf-8-sig")
            frames, tex_filename = _parse_plist(plist_data)
        except Exception:
            return False
        if not frames:
            return False
        png_name = tex_filename if tex_filename else entry.name.rsplit(".", 1)[0] + ".png"
        png_entry = self._find_entry(png_name)
        if not png_entry or len(png_entry.data) < 4 or png_entry.data[:4] != b'\x89BTF':
            return False
        try:
            atlas = KHUxBTF.from_bytes(png_entry.data).decode(use_canvas=True)
        except Exception:
            return False

        padding, label_h, max_thumb = 10, 14, 128
        sprites = []
        for frame_data in frames:
            name, x, y, w, h = frame_data[0], frame_data[1], frame_data[2], frame_data[3], frame_data[4]
            orig_w = frame_data[5] if len(frame_data) > 5 else w
            orig_h = frame_data[6] if len(frame_data) > 6 else h
            off_x = frame_data[7] if len(frame_data) > 7 else 0
            off_y = frame_data[8] if len(frame_data) > 8 else 0
            if w <= 0 or h <= 0:
                continue
            cropped = atlas.crop((x, y, x + w, y + h))
            if orig_w != w or orig_h != h:
                sprite = Image.new("RGBA", (int(orig_w), int(orig_h)), (0, 0, 0, 0))
                px = int((orig_w - w) / 2 + off_x)
                py = int((orig_h - h) / 2 - off_y)
                sprite.alpha_composite(cropped, (max(0, px), max(0, py)))
            else:
                sprite = cropped
            sprites.append((name, sprite, x, y, int(orig_w), int(orig_h)))
        if not sprites:
            return False

        self._plist_sprites = sprites
        self._plist_atlas = atlas
        self._plist_sprite_idx = -1
        self._render_plist_grid()
        return True

    def _plist_canvas_size(self):
        """Get the visible area of the preview widget for canvas sizing."""
        vp = self._image_preview.viewport().size()
        return max(vp.width(), 400), max(vp.height(), 300)

    def _render_plist_grid(self):
        """Render the sprite grid view for the current plist."""
        sprites = self._plist_sprites
        atlas = self._plist_atlas
        canvas_w, canvas_h = self._plist_canvas_size()
        padding, label_h, max_thumb = 10, 14, 128
        title_h = 28

        thumbs = []
        for name, sprite, ax, ay, ow, oh in sprites:
            s = min(max_thumb / max(ow, 1), max_thumb / max(oh, 1), 1.0)
            thumb = sprite.resize((max(1, int(ow * s)), max(1, int(oh * s))), Image.LANCZOS) if s < 1.0 else sprite
            thumbs.append((name, thumb, ow, oh))

        cell_w = max(t.width for _, t, _, _ in thumbs) + padding * 2
        cell_h = max(t.height for _, t, _, _ in thumbs) + padding * 2 + label_h
        cols = max(1, (canvas_w - padding) // cell_w)
        rows = (len(thumbs) + cols - 1) // cols
        content_h = rows * cell_h + padding + title_h
        canvas_h = max(canvas_h, content_h)

        canvas = Image.new("RGBA", (canvas_w, canvas_h), (30, 30, 30, 255))
        draw = ImageDraw.Draw(canvas)
        draw.text((padding, 6),
                  f"{len(sprites)} sprites from {atlas.size[0]}x{atlas.size[1]} atlas (double-click to inspect)",
                  fill=(160, 160, 160))
        for i, (name, thumb, ow, oh) in enumerate(thumbs):
            cx = (i % cols) * cell_w + padding
            cy = (i // cols) * cell_h + padding + title_h
            draw.rectangle([cx, cy, cx + cell_w - 1, cy + cell_h - 1],
                            fill=(45, 45, 48), outline=(80, 80, 80))
            canvas.alpha_composite(thumb,
                                   (cx + (cell_w - thumb.width) // 2, cy + padding))
            short_name = name.split(".")[0]
            if len(short_name) > cell_w // 7:
                short_name = short_name[:cell_w // 7 - 1] + ".."
            draw.text((cx + 3, cy + cell_h - label_h), short_name, fill=(130, 130, 130))

        self._plist_grid_cols = cols
        self._plist_grid_cell = (cell_w, cell_h)
        self._plist_grid_title_h = title_h
        self._plist_grid_padding = padding
        self._current_pil_image = canvas
        self._image_preview.set_pixmap(_pil_image_to_qpixmap(canvas))
        self._plist_prev_btn.setVisible(False)
        self._plist_grid_btn.setVisible(False)
        self._plist_next_btn.setVisible(False)

    def _render_plist_sprite_detail(self, idx):
        """Render a single sprite at full size with checkerboard background."""
        sprites = self._plist_sprites
        atlas = self._plist_atlas
        if idx < 0 or idx >= len(sprites):
            return
        self._plist_sprite_idx = idx
        name, sprite, sx, sy, ow, oh = sprites[idx]

        pad_top, pad_bottom = 30, 30
        canvas_w = ow + 2
        canvas_h = oh + pad_top + pad_bottom + 2

        canvas = Image.new("RGBA", (canvas_w, canvas_h), (30, 30, 30, 255))
        draw = ImageDraw.Draw(canvas)

        ix = 1
        iy = pad_top
        cell = 16
        c1, c2 = (42, 42, 42, 255), (55, 55, 55, 255)
        checker = Image.new("RGBA", (ow, oh), c1)
        for by in range(0, oh, cell):
            for bx in range(0, ow, cell):
                if (bx // cell + by // cell) % 2:
                    checker.paste(Image.new("RGBA", (min(cell, ow - bx), min(cell, oh - by)), c2), (bx, by))
        canvas.alpha_composite(checker, (ix, iy))
        canvas.alpha_composite(sprite, (ix, iy))
        draw.rectangle([ix - 1, iy - 1, ix + ow, iy + oh], outline=(80, 80, 80))

        draw.text((10, 10), f"[{idx + 1}/{len(sprites)}]  {name}", fill=(220, 220, 220))
        draw.text((10, canvas_h - 25),
                  f"Size: {ow}x{oh}   Atlas: ({sx}, {sy})   ← prev  |  next →  |  ESC = grid",
                  fill=(130, 130, 130))

        self._current_pil_image = canvas
        self._image_preview.set_pixmap(_pil_image_to_qpixmap(canvas))
        self._plist_prev_btn.setVisible(idx > 0)
        self._plist_grid_btn.setVisible(True)
        self._plist_next_btn.setVisible(idx < len(sprites) - 1)

    def _load_lwf_textures(self, entry: BGADEntry, lwf_info: dict) -> dict:
        """Load BTF textures referenced by an LWF, matching by directory prefix."""
        tex_imgs = {}
        if not HAS_BTF:
            return tex_imgs
        lwf_dir = entry.name.rsplit('/', 1)[0] + '/' if '/' in entry.name else ''
        resolved = lwf_info.get('texture_resolved', {})
        for tex_name in lwf_info.get('textures', []):
            decoded = resolved.get(tex_name, tex_name)
            basename = decoded.rsplit('/', 1)[-1] if '/' in decoded else decoded
            for candidate in [tex_name, decoded, lwf_dir + basename, basename]:
                e = self._find_entry(candidate)
                if e and len(e.data) >= 4 and e.data[:4] == b'\x89BTF':
                    try:
                        tex_imgs[tex_name] = KHUxBTF.from_bytes(e.data).decode(use_canvas=True).convert('RGBA')
                        tex_imgs[decoded] = tex_imgs[tex_name]
                        tex_imgs[basename] = tex_imgs[tex_name]
                    except Exception:
                        pass
                    break
        return tex_imgs

    def _render_lwf_visual(self, entry: BGADEntry) -> bool:
        """Render LWF animation frame in the Preview tab."""
        if not HAS_PIL:
            return False
        info = _parse_lwf_data(entry.data)
        if not info.get('_movies'):
            return False

        tex_imgs = self._load_lwf_textures(entry, info)
        self._lwf_info = info
        self._lwf_textures = tex_imgs
        self._lwf_frame = 0

        root_movie = info['_movies'][info['rootMovieId']] if info['rootMovieId'] < len(info['_movies']) else None
        if root_movie:
            self._lwf_total_frames = root_movie['frms']
        else:
            self._lwf_total_frames = 1

        self._lwf_render_current()
        return True

    def _lwf_render_current(self):
        info = getattr(self, '_lwf_info', None)
        if not info:
            return
        w = max(info.get('width', 200), 50)
        h = max(info.get('height', 200), 50)
        canvas = Image.new('RGBA', (w, h), (30, 30, 30, 255))
        _render_lwf_movie(info, info['rootMovieId'], self._lwf_frame,
                          self._lwf_textures, (1, 0, 0, 1, 0, 0),
                          canvas, w // 2, h // 2)
        self._current_pil_image = canvas
        self._image_preview.set_pixmap(_pil_image_to_qpixmap(canvas), keep_zoom=True)

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

        root = _cs_get_root(obj)
        if not isinstance(root, dict):
            return False

        show_hidden = bool(getattr(self, '_show_hidden_cb', None) and self._show_hidden_cb.isChecked())
        bx1, by1, bx2, by2 = _cs_bounding_box(root, show_hidden=show_hidden)
        pad = 1
        w = max(int(bx2 - bx1) + pad * 2, 50)
        h = max(int(by2 - by1) + pad * 2, 50)
        off_x = (-bx1 if bx1 < 0 else 0) + pad
        off_y = (-by1 if by1 < 0 else 0) + pad

        canvas = Image.new('RGBA', (w, h), (40, 40, 42, 255))
        self._cs_render_node(canvas, root, off_x, off_y, show_hidden)

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

    def _cs_render_node(self, canvas, node, px, py, show_hidden=False, _counter=None) -> bool:
        """Recursively render CocoStudio widgets. px/py = parent's anchor point in world coords."""
        if not isinstance(node, dict) or not HAS_BTF:
            return False
        if _counter is None:
            _counter = [0]
        widget_idx = _counter[0]
        _counter[0] += 1

        x, y, w, h, ax, ay, tex_path, cn, nm, s9, s9x, s9y, s9w, s9h, rotation, wsx, wsy, flip_x, flip_y, opacity = _cs_widget_props(node)
        anchor_wx = px + x
        anchor_wy = py + y

        opts_vis = node.get('options', node)
        is_json_hidden = not opts_vis.get('visible', True)

        if is_json_hidden and not show_hidden:
            for child in node.get('children', []):
                self._cs_render_node(canvas, child, anchor_wx, anchor_wy, show_hidden, _counter)
            return False

        layer_vis = self._get_layer_visibility()
        if layer_vis and widget_idx in layer_vis and not layer_vis[widget_idx]:
            for child in node.get('children', []):
                self._cs_render_node(canvas, child, anchor_wx, anchor_wy, show_hidden, _counter)
            return False

        draw_images = self._draw_images_cb.isChecked() if hasattr(self, '_draw_images_cb') else True
        draw_text = self._draw_text_cb.isChecked() if hasattr(self, '_draw_text_cb') else True
        draw_outlines = self._draw_outlines_cb.isChecked() if hasattr(self, '_draw_outlines_cb') else True
        bl_x = anchor_wx - w * ax
        bl_y = anchor_wy - h * ay
        pil_x = int(bl_x)
        pil_y = int(canvas.height - bl_y - h)

        rendered = False
        if cn == "Panel" and draw_images:
            opts_bg = node.get('options', node)
            ct = opts_bg.get('colorType', 0)
            bg_opacity = int(opts_bg.get('bgColorOpacity', 0))
            if ct > 0 and bg_opacity > 0 and w > 0 and h > 0:
                bgr = int(opts_bg.get('bgColorR', 150))
                bgg = int(opts_bg.get('bgColorG', 200))
                bgb = int(opts_bg.get('bgColorB', 255))
                bg_img = Image.new("RGBA", (w, h), (bgr, bgg, bgb, bg_opacity))
                bx, by = max(0, pil_x), max(0, pil_y)
                bw = min(w, canvas.width - bx)
                bh = min(h, canvas.height - by)
                if bw > 0 and bh > 0:
                    canvas.alpha_composite(bg_img.crop((0, 0, bw, bh)), (bx, by))

        if tex_path and draw_images:
            e = self._find_entry(tex_path)
            if e and len(e.data) >= 4 and e.data[:4] == b'\x89BTF':
                try:
                    img = KHUxBTF.from_bytes(e.data).decode(use_canvas=True)
                    ignore_size = node.get('options', node).get('ignoreSize', False)
                    if not ignore_size and w > 0 and h > 0 and (w, h) != img.size:
                        if s9:
                            img = _scale9_resize(img, w, h, s9x, s9y, s9w, s9h)
                        else:
                            img = img.resize((w, h), Image.LANCZOS)
                    if flip_x:
                        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                    if flip_y:
                        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                    if abs(wsx - 1) > 0.01 or abs(wsy - 1) > 0.01:
                        img = img.resize((max(1, int(img.width * abs(wsx))), max(1, int(img.height * abs(wsy)))), Image.LANCZOS)
                    if abs(rotation) > 0.1:
                        img = img.rotate(-rotation, expand=True, resample=Image.BICUBIC)
                    if opacity < 255:
                        img = ImageChops.multiply(img, Image.new("RGBA", img.size, (255, 255, 255, opacity)))
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

        if cn in ("Label", "TextField") and w > 0 and h > 0 and draw_text:
            opts = node.get("options", node)
            text = opts.get("text", "") or opts.get("placeHolder", "")
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

        if w > 10 and h > 10 and draw_outlines:
            draw = ImageDraw.Draw(canvas)
            rx = max(0, pil_x)
            ry = max(0, pil_y)
            rw = min(w, canvas.width - rx)
            rh = min(h, canvas.height - ry)
            if rw > 0 and rh > 0:
                draw.rectangle([rx, ry, rx + rw, ry + rh], outline=(90, 140, 200))
                if not rendered:
                    label = f"{cn}: {nm}"[:35] if nm else str(cn)
                    draw.text((rx + 3, ry + 2), label, fill=(140, 180, 220))

        children = node.get('children', [])
        if len(children) > 1:
            children = sorted(children, key=lambda c: c.get('options', c).get('ZOrder', 0))
        opts_clip = node.get('options', node)
        if opts_clip.get('clipAble', False) and w > 0 and h > 0:
            clip_canvas = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            clip_ox = anchor_wx - w * ax
            clip_oy = anchor_wy - h * ay
            for child in children:
                if self._cs_render_node(clip_canvas, child, anchor_wx - clip_ox, anchor_wy - clip_oy, show_hidden, _counter):
                    rendered = True
            cpx, cpy = int(clip_ox), int(canvas.height - clip_oy - h)
            sx, sy = 0, 0
            if cpx < 0:
                sx = -cpx; cpx = 0
            if cpy < 0:
                sy = -cpy; cpy = 0
            cw_clip = min(w - sx, canvas.width - cpx)
            ch_clip = min(h - sy, canvas.height - cpy)
            if cw_clip > 0 and ch_clip > 0:
                canvas.alpha_composite(clip_canvas.crop((sx, sy, sx + cw_clip, sy + ch_clip)), (cpx, cpy))
        else:
            for child in children:
                if self._cs_render_node(canvas, child, anchor_wx, anchor_wy, show_hidden, _counter):
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
    @staticmethod
    def _xml_to_html(text: str) -> str:
        """Convert XML text to syntax-highlighted HTML."""
        import html as _html
        import re as _re
        lines = text.split("\n")
        html_lines = []
        for line in lines:
            escaped = _html.escape(line)
            # Highlight tags
            escaped = _re.sub(
                r'(&lt;/?)(\w+)',
                r'\1<span style="color:#569CD6">\2</span>', escaped)
            # Highlight attribute names
            escaped = _re.sub(
                r' (\w+)(=)',
                r' <span style="color:#9CDCFE">\1</span>\2', escaped)
            # Highlight attribute values
            escaped = _re.sub(
                r'(&quot;[^&]*&quot;|"[^"]*")',
                r'<span style="color:#CE9178">\1</span>', escaped)
            # Highlight text content between tags
            escaped = _re.sub(
                r'(&gt;)([^<&]+)(&lt;)',
                r'\1<span style="color:#D4D4D4">\2</span>\3', escaped)
            html_lines.append(escaped)
        return "<br>".join(html_lines)

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

    def _show_plist_text_preview(self, entry: BGADEntry):
        """Show plist as pretty-printed, syntax-highlighted XML."""
        try:
            import xml.dom.minidom
            raw = entry.data.decode("utf-8-sig", errors="replace")
            dom = xml.dom.minidom.parseString(entry.data)
            pretty = dom.toprettyxml(indent="  ")
            lines = pretty.split("\n")
            if lines and lines[0].startswith("<?xml"):
                lines = lines[1:]
            pretty = "\n".join(lines)
            html = self._xml_to_html(pretty)
            self._preview_text.setHtml(
                f'<pre style="font-family:Consolas;font-size:10pt;color:{COLORS["fg"]};'
                f'background-color:{COLORS["text_bg"]};margin:0;white-space:pre-wrap;">'
                f'{html}</pre>'
            )
        except Exception:
            self._preview_text.setPlainText(entry.data.decode("utf-8-sig", errors="replace"))

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
    def _on_export_clicked(self):
        if not self.current_entry:
            return
        fmt = self.entry_formats.get(self.current_entry.name, "")
        menu = QMenu(self)
        if fmt == "scene":
            menu.addAction("Export PNG (as displayed)", self._export_scene_png)
            menu.addAction("Export PNG (clean, first frame)", lambda: self._export_scene_clean_png(frame=0))
            menu.addAction("Export PNG (clean, last frame)", lambda: self._export_scene_clean_png(frame=-1))
            menu.addAction("Export MP4 (as displayed)", self._export_scene_mp4)
            menu.addAction("Export MP4 (clean)", lambda: self._export_scene_mp4(clean=True))
        elif fmt == "anim":
            menu.addAction("Export MP4 (960x640 canvas)", self._export_anim_mp4)
            menu.addAction("Export MP4 (true size)", lambda: self._export_anim_mp4(true_size=True))
        elif fmt == "ui":
            menu.addAction("Export Scene PNG (as displayed)", self._export_ui_scene_png)
            menu.addAction("Export Image PNG (clean render)", self._export_ui_clean_png)
        else:
            menu.addAction("Export Entry...", self._export_entry)
        menu.exec(self._export_btn.mapToGlobal(self._export_btn.rect().bottomLeft()))

    def _export_default_name(self, suffix="", ext="png"):
        if self.current_entry:
            base = self.current_entry.name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            return f"{base}{suffix}.{ext}"
        return f"export{suffix}.{ext}"

    def _export_scene_png(self):
        if self._current_pil_image:
            path, _ = QFileDialog.getSaveFileName(self, "Export Scene PNG", self._export_default_name("_frame"), "PNG Image (*.png)")
            if path:
                self._current_pil_image.save(path, "PNG")
                self._status_left.setText(f"Exported: {os.path.basename(path)}")

    def _export_ui_scene_png(self):
        if self._current_pil_image:
            path, _ = QFileDialog.getSaveFileName(self, "Export Scene PNG", self._export_default_name("_scene"), "PNG Image (*.png)")
            if path:
                self._current_pil_image.save(path, "PNG")
                self._status_left.setText(f"Exported: {os.path.basename(path)}")

    def _export_scene_clean_png(self, frame=0):
        if not getattr(self, '_scene_obj', None) or not HAS_PIL:
            return
        saved = {}
        for attr in ('_draw_images_cb', '_draw_text_cb', '_draw_outlines_cb', '_show_hidden_cb'):
            cb = getattr(self, attr, None)
            if cb:
                saved[attr] = cb.isChecked()
                cb.blockSignals(True)
        self._draw_images_cb.setChecked(True)
        self._draw_text_cb.setChecked(True)
        self._draw_outlines_cb.setChecked(False)
        if hasattr(self, '_show_hidden_cb'):
            self._show_hidden_cb.setChecked(False)
        saved_frames = []
        saved_modes = []
        for ctrl in self._scene_anim_controls:
            saved_frames.append(ctrl['frame'])
            saved_modes.append(ctrl['mode_combo'].currentIndex())
            ctrl['mode_combo'].blockSignals(True)
            if ctrl['mode_combo'].currentIndex() == 0 and ctrl['anim_data'].get('mov_data'):
                ctrl['mode_combo'].setCurrentIndex(1)
            mov_idx = ctrl['mov_combo'].currentIndex()
            movs = ctrl['anim_data'].get('mov_data', [])
            if mov_idx < len(movs):
                dr = movs[mov_idx].get('dr', 1)
                ctrl['frame'] = 0 if frame == 0 else dr - 1
        self._render_scene_with_anims()
        export_img = self._current_pil_image.copy() if self._current_pil_image else None
        for attr, val in saved.items():
            cb = getattr(self, attr)
            cb.setChecked(val)
            cb.blockSignals(False)
        for i, ctrl in enumerate(self._scene_anim_controls):
            if i < len(saved_frames):
                ctrl['frame'] = saved_frames[i]
            if i < len(saved_modes):
                ctrl['mode_combo'].setCurrentIndex(saved_modes[i])
                ctrl['mode_combo'].blockSignals(False)
        self._render_scene_with_anims()
        suffix = "_first" if frame == 0 else "_last"
        if export_img:
            path, _ = QFileDialog.getSaveFileName(self, "Export Clean Scene PNG", self._export_default_name(suffix), "PNG Image (*.png)")
            if path:
                export_img.save(path, "PNG")
                self._status_left.setText(f"Exported: {os.path.basename(path)}")

    def _export_ui_clean_png(self):
        if not self.current_entry or not HAS_PIL:
            return
        try:
            obj = json.loads(self.current_entry.data.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, ValueError):
            return
        root = _cs_get_root(obj)
        if not isinstance(root, dict):
            return
        bx1, by1, bx2, by2 = _cs_bounding_box(root, show_hidden=False)
        pad = 1
        w = max(int(bx2 - bx1) + pad * 2, 50)
        h = max(int(by2 - by1) + pad * 2, 50)
        off_x = (-bx1 if bx1 < 0 else 0) + pad
        off_y = (-by1 if by1 < 0 else 0) + pad
        canvas = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        saved = {}
        for attr in ('_draw_images_cb', '_draw_text_cb', '_draw_outlines_cb', '_show_hidden_cb'):
            cb = getattr(self, attr, None)
            if cb:
                saved[attr] = cb.isChecked()
                cb.blockSignals(True)
        self._draw_images_cb.setChecked(True)
        self._draw_text_cb.setChecked(True)
        self._draw_outlines_cb.setChecked(False)
        if hasattr(self, '_show_hidden_cb'):
            self._show_hidden_cb.setChecked(False)
        self._cs_render_node(canvas, root, off_x, off_y, show_hidden=False)
        path, _ = QFileDialog.getSaveFileName(self, "Export Clean Image PNG", self._export_default_name("_clean"), "PNG Image (*.png)")
        if path:
            canvas.save(path, "PNG")
            self._status_left.setText(f"Exported: {os.path.basename(path)}")
        for attr, val in saved.items():
            cb = getattr(self, attr)
            cb.setChecked(val)
            cb.blockSignals(False)

    def _export_anim_mp4(self, true_size=False):
        if not hasattr(self, '_anim_data') or not HAS_PIL:
            return
        if hasattr(self, '_anim_timer') and self._anim_timer.isActive():
            self._anim_timer.stop()
            self._anim_play_btn.setText("Play")
            self._anim_playing = False
        mov_idx = getattr(self, '_anim_movement_idx', 0)
        movs = self._anim_data.get('mov_data', [])
        if mov_idx >= len(movs):
            return
        mov = movs[mov_idx]
        dr = mov.get('dr', 1)
        mov_name = mov.get('name', 'anim')

        if true_size:
            tex_data = getattr(self, '_anim_texture_data', []) or []
            max_w = max((int(td.get('width', 64)) for td in tex_data), default=128)
            max_h = max((int(td.get('height', 64)) for td in tex_data), default=128)
            cw = max_w * 4
            ch = max_h * 4
            cw = min(cw, 1920)
            ch = min(ch, 1080)
            cw += cw % 2
            ch += ch % 2
            suffix = f"_{mov_name}_true"
        else:
            cw, ch = 960, 640
            suffix = f"_{mov_name}"

        path, _ = QFileDialog.getSaveFileName(self, "Export Animation MP4", self._export_default_name(suffix, "mp4"), "MP4 Video (*.mp4)")
        if not path:
            return

        def frame_gen(progress):
            bg = Image.new("RGBA", (cw, ch), (30, 30, 30, 255))
            anim_single = {'mov_data': [mov]}
            for f in range(dr):
                frame_img = _render_anim_frame(anim_single, self._anim_armature,
                                                self._anim_sprites, f,
                                                canvas_size=(cw, ch),
                                                texture_data=getattr(self, '_anim_texture_data', None))
                canvas = bg.copy()
                canvas.alpha_composite(frame_img, (0, 0))
                progress.setValue(f)
                if progress.wasCanceled():
                    return
                yield canvas.convert("RGB")
        self._export_mp4_piped(path, dr, cw, ch, frame_gen)

    def _export_scene_mp4(self, clean=False):
        if not getattr(self, '_scene_obj', None) or not HAS_PIL:
            return
        was_playing = hasattr(self, '_scene_anim_timer') and self._scene_anim_timer.isActive()
        if was_playing:
            self._scene_anim_timer.stop()
            self._scene_play_btn.setText("Play")
        max_dr = 1
        for ctrl in self._scene_anim_controls:
            mode = ctrl['mode_combo'].currentIndex()
            if mode == 0:
                continue
            mov_idx = ctrl['mov_combo'].currentIndex()
            movs = ctrl['anim_data'].get('mov_data', [])
            if mov_idx < len(movs):
                max_dr = max(max_dr, movs[mov_idx].get('dr', 1))
        suffix = "_scene_clean" if clean else "_scene"
        path, _ = QFileDialog.getSaveFileName(self, "Export Scene MP4", self._export_default_name(suffix, "mp4"), "MP4 Video (*.mp4)")
        if not path:
            return

        saved_toggles = {}
        if clean:
            for attr in ('_draw_images_cb', '_draw_text_cb', '_draw_outlines_cb', '_show_hidden_cb'):
                cb = getattr(self, attr, None)
                if cb:
                    saved_toggles[attr] = cb.isChecked()
                    cb.blockSignals(True)
            self._draw_images_cb.setChecked(True)
            self._draw_text_cb.setChecked(True)
            self._draw_outlines_cb.setChecked(False)
            self._show_hidden_cb.setChecked(False)

        def frame_gen(progress):
            for f in range(max_dr):
                for ctrl in self._scene_anim_controls:
                    mode = ctrl['mode_combo'].currentIndex()
                    if mode in (2, 3):
                        ctrl['frame'] = f % ctrl['anim_data'].get('mov_data', [{}])[ctrl['mov_combo'].currentIndex()].get('dr', max_dr)
                    elif mode == 1:
                        mi = ctrl['mov_combo'].currentIndex()
                        ms = ctrl['anim_data'].get('mov_data', [])
                        if mi < len(ms):
                            ctrl['frame'] = ms[mi].get('dr', 1) - 1
                self._render_scene_with_anims()
                progress.setValue(f)
                if progress.wasCanceled():
                    return
                if self._current_pil_image:
                    yield self._current_pil_image.convert("RGB")
        self._export_mp4_piped(path, max_dr, 960, 640, frame_gen)

        if clean:
            for attr, val in saved_toggles.items():
                cb = getattr(self, attr)
                cb.setChecked(val)
                cb.blockSignals(False)
            self._render_scene_with_anims()

    def _export_mp4_piped(self, path, total_frames, w, h, frame_generator):
        """Export MP4 by piping raw frames to ffmpeg stdin."""
        import subprocess
        from PyQt6.QtWidgets import QProgressDialog

        progress = QProgressDialog("Exporting video...", "Cancel", 0, total_frames, self)
        progress.setWindowTitle("Export MP4")
        progress.setMinimumDuration(0)
        progress.setValue(0)

        import tempfile
        err_file = tempfile.NamedTemporaryFile(suffix=".log", delete=False, mode='w')
        err_path = err_file.name
        err_file.close()

        proc = subprocess.Popen([
            "ffmpeg", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{w}x{h}", "-r", "60",
            "-i", "pipe:",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "18", "-preset", "fast",
            path
        ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
           stderr=open(err_path, 'w'))

        try:
            for frame in frame_generator(progress):
                if progress.wasCanceled():
                    proc.kill()
                    break
                proc.stdin.write(frame.tobytes())
                QApplication.processEvents()
            proc.stdin.close()
            progress.setLabelText("Encoding video...")
            progress.setValue(total_frames)
            QApplication.processEvents()
            while proc.poll() is None:
                QApplication.processEvents()
                import time
                time.sleep(0.05)
            if proc.returncode == 0 and not progress.wasCanceled():
                size = os.path.getsize(path) if os.path.exists(path) else 0
                self._status_left.setText(f"Exported: {os.path.basename(path)} ({_format_size(size)})")
            elif progress.wasCanceled():
                self._status_left.setText("Export canceled")
                try:
                    os.unlink(path)
                except OSError:
                    pass
            else:
                try:
                    err = open(err_path, 'r').read()[-300:]
                except Exception:
                    err = "Unknown error"
                QMessageBox.critical(self, "Export Error", f"ffmpeg error:\n{err}")
        except Exception as e:
            proc.kill()
            QMessageBox.critical(self, "Export Error", str(e))
        finally:
            progress.close()
            try:
                os.unlink(err_path)
            except OSError:
                pass

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
