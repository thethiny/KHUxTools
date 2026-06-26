from dataclasses import dataclass
import struct
from typing import List, Tuple


@dataclass
class JMPEntry:
    target_map: str
    x: int
    y: int


@dataclass
class JMPData:
    magic: bytes
    entry_count: int
    entries: List[JMPEntry]
    raw_data: bytes


def parse_jmp(data: bytes) -> JMPData:
    if len(data) < 8 or data[:4] != b"JMP\x00":
        raise ValueError("Not a valid JMP file")

    entry_count = struct.unpack_from("<I", data, 4)[0]

    entries = []
    off = 8
    for _ in range(entry_count):
        if off + 4 > len(data):
            break
        name_len = struct.unpack_from("<I", data, off)[0]
        off += 4
        if off + name_len > len(data):
            break
        name = data[off:off + name_len].decode("ascii", errors="replace").rstrip("\x00")
        off += name_len
        x = struct.unpack_from("<i", data, off)[0] if off + 4 <= len(data) else 0
        off += 4
        y = struct.unpack_from("<i", data, off)[0] if off + 4 <= len(data) else 0
        off += 4
        entries.append(JMPEntry(target_map=name, x=x, y=y))

    return JMPData(
        magic=data[:4], entry_count=entry_count,
        entries=entries, raw_data=data,
    )
