from dataclasses import dataclass, field
import struct
from typing import List


@dataclass
class MAPData:
    magic: bytes
    version: int
    name_field_size: int
    map_name: str
    num_sections: int
    section_offsets: List[int]
    raw_data: bytes

    @property
    def data_start(self) -> int:
        return 12 + self.name_field_size


def parse_map(data: bytes) -> MAPData:
    if len(data) < 12 or data[:4] != b"MAP\x00":
        raise ValueError("Not a valid MAP file")

    version = struct.unpack_from("<I", data, 4)[0]
    name_field_size = struct.unpack_from("<I", data, 8)[0]

    name_end = 12
    if name_field_size > 0 and 12 + name_field_size <= len(data):
        raw_name = data[12:12 + name_field_size]
        null_idx = raw_name.find(0)
        if null_idx >= 0:
            raw_name = raw_name[:null_idx]
        map_name = raw_name.decode("ascii", errors="replace")
        name_end = 12 + name_field_size
    else:
        map_name = ""

    num_sections = 0
    section_offsets = []
    if name_end + 4 <= len(data):
        num_sections = struct.unpack_from("<I", data, name_end)[0]
        off = name_end + 4
        for i in range(min(num_sections, 64)):
            if off + 4 > len(data):
                break
            section_offsets.append(struct.unpack_from("<I", data, off)[0])
            off += 4

    return MAPData(
        magic=data[:4], version=version,
        name_field_size=name_field_size, map_name=map_name,
        num_sections=num_sections, section_offsets=section_offsets,
        raw_data=data,
    )
