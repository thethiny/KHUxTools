from dataclasses import dataclass
from io import BufferedReader
import struct


@dataclass
class BGIHeader:
    magic: bytes   # 0x00  4 bytes  "\x89BGI"
    version: int   # 0x04  u32     must be 3
    flags: int     # 0x08  u32     bit 0 = encrypted

    _fmt = "<4sII"
    _struct = struct.Struct(_fmt)
    _magic = b"\x89BGI"

    @classmethod
    def from_bytes(cls, data: bytes) -> "BGIHeader":
        unpacked = cls._struct.unpack(data)
        obj = cls(*unpacked)
        if obj.magic != cls._magic:
            raise ValueError(f"Invalid BGI magic: {obj.magic!r} (expected {cls._magic!r})")
        return obj

    @classmethod
    def from_file(cls, file: BufferedReader) -> "BGIHeader":
        data = file.read(cls._struct.size)
        if len(data) < cls._struct.size:
            raise ValueError(f"Not enough data for BGI header (got {len(data)} bytes)")
        return cls.from_bytes(data)

    @property
    def encrypted(self) -> bool:
        return bool(self.flags & 1)


@dataclass
class BGIEntry:
    offset: int
    size: int


@dataclass
class BGINameEntry:
    name: str
    entry_index: int
