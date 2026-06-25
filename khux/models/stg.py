from dataclasses import dataclass
from io import BufferedReader
import struct


@dataclass
class STGHeader:
    magic: bytes        # 0x00  4 bytes  "STG\0"
    version: int        # 0x04  u32
    count: int          # 0x08  u32
    data_offset: int    # 0x0C  u32

    _fmt = "<4sIII"
    _struct = struct.Struct(_fmt)
    _magic = b"STG\x00"

    @classmethod
    def from_bytes(cls, data: bytes) -> "STGHeader":
        unpacked = cls._struct.unpack_from(data)
        obj = cls(*unpacked)
        if obj.magic != cls._magic:
            raise ValueError(f"Invalid STG magic: {obj.magic!r}")
        return obj

    @classmethod
    def from_file(cls, file: BufferedReader) -> "STGHeader":
        data = file.read(cls._struct.size)
        if len(data) < cls._struct.size:
            raise ValueError(f"Not enough data for STG header (got {len(data)} bytes)")
        return cls.from_bytes(data)
