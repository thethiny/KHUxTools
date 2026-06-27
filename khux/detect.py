from io import BufferedReader

MAGIC_TABLE = {
    b"\x89BTF": "btf",
    b"LWF\x00": "lwf",
    b"\x5D\xF9\x00\x00": "lwf",
    b"STG\x00": "stg",
    b"MAP\x00": "map",
    b"\x89BGI": "bgi",
    b"BGAD": "bgad",
    b"AKB ": "akb",
    b"JMP\x00": "jmp",
    b"BMI\x00": "bmi",
    b"CLS\x00": "cls",
    b"CHP\x00": "chp",
}


def _is_printable_text(data: bytes) -> bool:
    try:
        text = data.decode("utf-8")
        return all(c.isprintable() or c in "\r\n\t" for c in text)
    except (UnicodeDecodeError, ValueError):
        return False


def detect_format(data: bytes) -> str:
    if len(data) < 4:
        if len(data) > 0 and _is_printable_text(data):
            return "text"
        return "unknown"
    magic = data[:4]
    fmt = MAGIC_TABLE.get(magic)
    if fmt:
        return fmt
    if data[:3] == b"\xEF\xBB\xBF":
        return "plist"
    if data[:5] == b"<?xml":
        return "plist"
    if data[:1] == b"<" and len(data) > 8 and (b"</" in data[:256] or b"<dict" in data[:256] or b"<plist" in data[:256]):
        return "plist"
    if data[:1] in (b"[", b"{") and len(data) > 4:
        return "json"
    if len(data) <= 4 and _is_printable_text(data):
        return "text"
    if len(data) == 4:
        return "index"
    if _is_printable_text(data[:64]):
        return "text"
    return "unknown"


def detect_format_from_file(file_handle: BufferedReader) -> str:
    pos = file_handle.tell()
    magic = file_handle.read(4)
    file_handle.seek(pos)
    return detect_format(magic)
