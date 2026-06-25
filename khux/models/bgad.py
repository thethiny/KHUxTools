from dataclasses import dataclass
from io import BufferedReader
import struct


@dataclass
class BGADHeader:
    magic: bytes          # 0x00  4 bytes
    version: int          # 0x04  u16 (must be 1 or 2)
    flags: int            # 0x06  u16 (bit 2 = has 8-byte nonce for mode 3)
    header_size: int      # 0x08  u16 (always 24)
    name_length: int      # 0x0A  u16 (also LCG seed for data decryption in modes 1,2)
    encryption_mode: int  # 0x0C  u16 (0=none, 1=byte LCG, 2=dword LCG, 3=ChaCha20)
    compression_mode: int # 0x0E  u16 (0=none, 2=zlib)
    data_size: int        # 0x10  u32 (LCG seed for name decryption; includes 8-byte nonce for mode 3)
    decompressed_size: int # 0x14  u32

    _fmt = "<4sHHHHHHII"
    _struct = struct.Struct(_fmt)
    _magic = b"BGAD"

    @classmethod
    def from_bytes(cls, data: bytes) -> "BGADHeader":
        unpacked = cls._struct.unpack(data)
        obj = cls(*unpacked)
        if obj.magic != cls._magic:
            raise ValueError(f"Invalid BGAD magic: {obj.magic!r} (expected {cls._magic!r})")
        if obj.version not in (1, 2):
            raise ValueError(f"Unsupported BGAD version: {obj.version}")
        return obj

    @classmethod
    def from_file(cls, file: BufferedReader) -> "BGADHeader":
        data = file.read(cls._struct.size)
        if len(data) < cls._struct.size:
            raise ValueError(f"Not enough data for BGAD header (got {len(data)} bytes)")
        return cls.from_bytes(data)

    @property
    def has_nonce(self) -> bool:
        return bool(self.flags & 4)

    @property
    def payload_size(self) -> int:
        if self.has_nonce and self.encryption_mode == 3:
            return self.data_size - 8
        return self.data_size
