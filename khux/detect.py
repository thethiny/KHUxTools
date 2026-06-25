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


def detect_format(data: bytes) -> str:
    if len(data) < 4:
        return "unknown"
    magic = data[:4]
    fmt = MAGIC_TABLE.get(magic)
    if fmt:
        return fmt
    if data[:3] == b"\xEF\xBB\xBF" or data[:1] == b"<":
        return "plist"
    if len(data) == 4:
        return "index"
    return "unknown"


def detect_format_from_file(file_handle: BufferedReader) -> str:
    pos = file_handle.tell()
    magic = file_handle.read(4)
    file_handle.seek(pos)
    return detect_format(magic)
