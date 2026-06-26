from dataclasses import dataclass
import struct
from typing import List


@dataclass
class CHPData:
    magic: bytes
    total_size: int
    grid_size: int
    grid: List[int]
    raw_data: bytes


def parse_chp(data: bytes) -> CHPData:
    if len(data) < 12 or data[:4] != b"CHP\x00":
        raise ValueError("Not a valid CHP file")

    total_size = struct.unpack_from("<I", data, 4)[0]
    grid_size = struct.unpack_from("<I", data, 8)[0]

    grid = list(data[12:12 + grid_size])

    return CHPData(
        magic=data[:4], total_size=total_size,
        grid_size=grid_size, grid=grid,
        raw_data=data,
    )
