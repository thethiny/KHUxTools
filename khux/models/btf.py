from dataclasses import dataclass
from io import BufferedReader
import struct


@dataclass
class BTFHeader:
    magic: bytes          # 0x00  4 bytes  "\x89BTF"
    skip: bytes           # 0x04  2 bytes
    unknown1: int         # 0x06  u32
    unknown2: int         # 0x0A  u32
    image_format: int     # 0x0E  u32 (flags: bit 16 = indexed, bit 19 = compressed)
    unknown4: int         # 0x12  u32
    canvas_width: int     # 0x16  u16
    canvas_height: int    # 0x18  u16
    canvas_offset_x: int  # 0x1A  u16
    canvas_offset_y: int  # 0x1C  u16
    image_width: int      # 0x1E  u16
    image_height: int     # 0x20  u16

    _fmt = "<4s2sIIIIHHHHHH"
    _struct = struct.Struct(_fmt)
    _magic = b"\x89BTF"

    FLAG_INDEXED = 0x010000
    FLAG_COMPRESSED = 0x080000

    @property
    def is_indexed(self) -> bool:
        return bool(self.image_format & self.FLAG_INDEXED)

    @property
    def is_compressed(self) -> bool:
        return bool(self.image_format & self.FLAG_COMPRESSED)

    @classmethod
    def from_bytes(cls, data: bytes) -> "BTFHeader":
        unpacked = cls._struct.unpack_from(data)
        obj = cls(*unpacked)
        if obj.magic != cls._magic:
            raise ValueError(f"Invalid BTF magic: {obj.magic!r}")
        return obj

    @classmethod
    def from_file(cls, file: BufferedReader) -> "BTFHeader":
        data = file.read(cls._struct.size)
        if len(data) < cls._struct.size:
            raise ValueError(f"Not enough data for BTF header (got {len(data)} bytes)")
        return cls.from_bytes(data)
