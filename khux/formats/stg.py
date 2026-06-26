from dataclasses import dataclass
import struct
from typing import List


@dataclass
class STGData:
    magic: bytes
    version: int
    world_id: int
    stage_id: int
    quest_id: int
    field1: int
    field2: int
    field3: int
    field4: int
    field5: int
    raw_data: bytes
    extra_fields: List[int]

    @property
    def size_class(self) -> str:
        n = len(self.raw_data)
        if n <= 28:
            return "small"
        elif n <= 40:
            return "medium"
        return "full"


def parse_stg(data: bytes) -> STGData:
    if len(data) < 16 or data[:4] != b"STG\x00":
        raise ValueError("Not a valid STG file")

    version = struct.unpack_from("<I", data, 4)[0]
    world_id = struct.unpack_from("<I", data, 8)[0]
    stage_id = struct.unpack_from("<I", data, 12)[0]

    quest_id = struct.unpack_from("<I", data, 16)[0] if len(data) >= 20 else 0
    f1 = struct.unpack_from("<I", data, 20)[0] if len(data) >= 24 else 0
    f2 = struct.unpack_from("<I", data, 24)[0] if len(data) >= 28 else 0
    f3 = struct.unpack_from("<I", data, 28)[0] if len(data) >= 32 else 0
    f4 = struct.unpack_from("<I", data, 32)[0] if len(data) >= 36 else 0
    f5 = struct.unpack_from("<I", data, 36)[0] if len(data) >= 40 else 0

    extra = []
    off = 40
    while off + 4 <= len(data):
        extra.append(struct.unpack_from("<I", data, off)[0])
        off += 4

    return STGData(
        magic=data[:4], version=version,
        world_id=world_id, stage_id=stage_id, quest_id=quest_id,
        field1=f1, field2=f2, field3=f3, field4=f4, field5=f5,
        raw_data=data, extra_fields=extra,
    )
