from dataclasses import dataclass
import struct
from typing import List


@dataclass
class BMIData:
    magic: bytes
    map_width: int
    map_height: int
    map_name: str
    bg_name: str
    strings: List[str]
    raw_data: bytes


def _read_cstring(data: bytes, offset: int, max_len: int = 32) -> str:
    end = offset
    while end < min(offset + max_len, len(data)) and data[end] != 0:
        end += 1
    return data[offset:end].decode("ascii", errors="replace")


def parse_bmi(data: bytes) -> BMIData:
    if len(data) < 8 or data[:4] != b"BMI\x00":
        raise ValueError("Not a valid BMI file")

    map_width = struct.unpack_from("<H", data, 40)[0] if len(data) >= 42 else 0
    map_height = struct.unpack_from("<H", data, 42)[0] if len(data) >= 44 else 0

    map_name = _read_cstring(data, 16) if len(data) >= 20 else ""
    bg_name = _read_cstring(data, 56) if len(data) >= 60 else ""

    strings = []
    i = 4
    while i < len(data):
        if 0x20 <= data[i] < 0x7F:
            end = i
            while end < len(data) and 0x20 <= data[end] < 0x7F:
                end += 1
            if end - i >= 3:
                strings.append(data[i:end].decode("ascii", errors="replace"))
            i = end
        else:
            i += 1

    return BMIData(
        magic=data[:4], map_width=map_width, map_height=map_height,
        map_name=map_name, bg_name=bg_name, strings=strings,
        raw_data=data,
    )
